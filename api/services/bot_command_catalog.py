from api.models.bot_commands import (
    BotCommandChoiceModel,
    BotCommandComponentModel,
    BotCommandDocModel,
    BotCommandParameterModel,
)


def _choice(name: str, value: str | None = None) -> BotCommandChoiceModel:
    return BotCommandChoiceModel(name=name, value=value or name)


def _param(
    name: str,
    type_: str,
    description: str,
    *,
    required: bool = True,
    default: str | None = None,
    choices: list[BotCommandChoiceModel] | None = None,
    autocomplete: bool = False,
) -> BotCommandParameterModel:
    return BotCommandParameterModel(
        name=name,
        type=type_,
        required=required,
        description=description,
        default=default,
        choices=choices or [],
        autocomplete=autocomplete,
    )


def _component(type_: str, label: str, description: str) -> BotCommandComponentModel:
    return BotCommandComponentModel(type=type_, label=label, description=description)


RULE_PARAM = _param("rule", "string", "Server moderation rule selected from active rules.", autocomplete=True)
CASE_PARAM = _param("case", "string", "Existing open case, or a special create-new case option when available.", required=False, autocomplete=True)
USER_PARAM = _param("user", "member", "Target Discord member.")
COMMENTARY_PARAM = _param("commentary", "string", "Optional moderator context stored with the action.", required=False)
ACTION_ID_PARAM = _param("action_id", "string", "Moderation action UUID.")
CASE_ID_PARAM = _param("case", "string", "Moderation case UUID selected from autocomplete.", autocomplete=True)
DURATION_CHOICES = [
    _choice("server default", "default"),
    _choice("10 minutes", "10m"),
    _choice("30 minutes", "30m"),
    _choice("1 hour", "1h"),
    _choice("6 hours", "6h"),
    _choice("12 hours", "12h"),
    _choice("1 day", "1d"),
    _choice("3 days", "3d"),
    _choice("1 week", "1w"),
    _choice("2 weeks", "2w"),
    _choice("30 days", "30d"),
]
DURATION_UNIT_CHOICES = [_choice("minutes"), _choice("hours"), _choice("days"), _choice("weeks"), _choice("months")]
MESSAGE_CLEANUP_CHOICES = [
    _choice("15 minutes", "15"),
    _choice("1 hour", "60"),
    _choice("6 hours", "360"),
    _choice("24 hours", "1440"),
    _choice("7 days", "10080"),
]
DELETE_MESSAGES_PARAM = _param(
    "delete_messages",
    "choice",
    "Optional recent-message window to delete logged target-user messages while applying the action.",
    required=False,
    choices=MESSAGE_CLEANUP_CHOICES,
)
DELETE_MESSAGE_LIMIT_PARAM = _param(
    "delete_message_limit",
    "integer",
    "Maximum messages to delete for delete_messages; defaults to 25 and is capped at 100.",
    required=False,
    default="25",
)
DELETE_MESSAGE_CHANNEL_PARAM = _param(
    "delete_message_channel",
    "text_channel",
    "Optional channel scope for command-triggered message cleanup.",
    required=False,
)


BOT_COMMANDS: tuple[BotCommandDocModel, ...] = (
    BotCommandDocModel(
        id="mod.warn",
        name="warn",
        qualified_name="mod warn",
        invoke="/mod warn",
        category="moderation-actions",
        summary="Warn a member, cite a server rule, and log the moderation action.",
        required_permissions=["moderate_members"],
        parameters=[
            USER_PARAM,
            RULE_PARAM,
            COMMENTARY_PARAM,
            CASE_PARAM,
            DELETE_MESSAGES_PARAM,
            DELETE_MESSAGE_LIMIT_PARAM,
            DELETE_MESSAGE_CHANNEL_PARAM,
        ],
        components=[
            _component("autocomplete", "rule", "Searches active server moderation rules."),
            _component("autocomplete", "case", "Suggests open cases for the selected target member."),
            _component("choices", "delete_messages", "Optional recent-message cleanup windows from 15 minutes to 7 days."),
        ],
        workflow=[
            "Validates the command is run in a server.",
            "Loads active server rules and requires a valid selected rule.",
            "Validates the moderator can act on the target member.",
            "Creates or links a moderation case when requested, creates a warn action, and commits it.",
            "When delete_messages is set, deletes recent logged messages from the target user and links them as deleted-message evidence.",
            "Posts a public action notice in the channel and an ephemeral moderator receipt.",
        ],
        notes=[
            "Commands support recent target-user cleanup. The dashboard additionally supports selecting specific logged messages.",
        ],
    ),
    BotCommandDocModel(
        id="mod.mute",
        name="mute",
        qualified_name="mod mute",
        invoke="/mod mute",
        category="moderation-actions",
        summary="Apply the configured mute role for a selected duration and log the action.",
        required_permissions=["moderate_members"],
        parameters=[
            USER_PARAM,
            RULE_PARAM,
            _param("duration", "choice", "Preset duration. Defaults to the server mute default when omitted.", required=False, choices=DURATION_CHOICES),
            _param("duration_value", "integer", "Custom duration amount from 1 to 999.", required=False),
            _param("duration_unit", "choice", "Unit for duration_value. Defaults to minutes when duration_value is used.", required=False, choices=DURATION_UNIT_CHOICES),
            COMMENTARY_PARAM,
            CASE_PARAM,
            DELETE_MESSAGES_PARAM,
            DELETE_MESSAGE_LIMIT_PARAM,
            DELETE_MESSAGE_CHANNEL_PARAM,
        ],
        components=[
            _component("choices", "duration", "Server default plus fixed presets from 10 minutes to 30 days."),
            _component("choices", "duration_unit", "Minutes, hours, days, weeks, or months."),
            _component("autocomplete", "rule", "Searches active server moderation rules."),
            _component("autocomplete", "case", "Suggests open cases for the selected target member."),
            _component("choices", "delete_messages", "Optional recent-message cleanup windows from 15 minutes to 7 days."),
        ],
        workflow=[
            "Loads moderation settings and requires a configured mute role.",
            "Checks the mute role exists and is below the bot role.",
            "Resolves the duration from preset or custom fields within the server maximum.",
            "When delete_messages is set, deletes recent logged messages from the target user and links them as deleted-message evidence.",
            "Logs the mute action, applies Discord effects, posts a public notice, and returns an ephemeral receipt.",
        ],
        notes=[
            "Commands support recent target-user cleanup. The dashboard additionally supports selecting specific logged messages.",
        ],
    ),
    BotCommandDocModel(
        id="mod.unmute",
        name="unmute",
        qualified_name="mod unmute",
        invoke="/mod unmute",
        category="moderation-actions",
        summary="Remove the configured mute role and close active mute actions for a member.",
        required_permissions=["moderate_members"],
        parameters=[USER_PARAM, _param("reason", "string", "Optional reason for the manual unmute.", required=False)],
        workflow=[
            "Validates the target member.",
            "Removes the configured mute role when present.",
            "Deactivates active mute actions for the user.",
            "Writes the moderation log when a log channel is configured, posts public notice, and sends an ephemeral receipt.",
        ],
    ),
    BotCommandDocModel(
        id="mod.kick",
        name="kick",
        qualified_name="mod kick",
        invoke="/mod kick",
        category="moderation-actions",
        summary="Kick a member and log the action with a rule citation.",
        required_permissions=["kick_members"],
        parameters=[USER_PARAM, RULE_PARAM, COMMENTARY_PARAM, CASE_PARAM],
        components=[
            _component("autocomplete", "rule", "Searches active server moderation rules."),
            _component("autocomplete", "case", "Suggests open cases for the selected target member."),
        ],
        workflow=[
            "Validates target hierarchy and selected rule.",
            "Creates the moderation action through the shared action service with Discord effects enabled.",
            "Posts public notice and an ephemeral moderator receipt.",
        ],
    ),
    BotCommandDocModel(
        id="mod.ban",
        name="ban",
        qualified_name="mod ban",
        invoke="/mod ban",
        category="moderation-actions",
        summary="Ban a member permanently or for a selected duration and log the action.",
        required_permissions=["ban_members"],
        parameters=[
            USER_PARAM,
            RULE_PARAM,
            _param("duration", "choice", "Permanent by default, or a fixed preset when selected.", required=False, choices=[_choice("permanent", "permanent"), *DURATION_CHOICES[1:]]),
            _param("duration_value", "integer", "Custom duration amount from 1 to 999.", required=False),
            _param("duration_unit", "choice", "Unit for duration_value. Defaults to minutes when duration_value is used.", required=False, choices=DURATION_UNIT_CHOICES),
            COMMENTARY_PARAM,
            CASE_PARAM,
            DELETE_MESSAGES_PARAM,
            DELETE_MESSAGE_LIMIT_PARAM,
            DELETE_MESSAGE_CHANNEL_PARAM,
        ],
        components=[
            _component("choices", "duration", "Permanent plus fixed presets from 10 minutes to 30 days."),
            _component("autocomplete", "rule", "Searches active server moderation rules."),
            _component("autocomplete", "case", "Suggests open cases for the selected target member."),
            _component("choices", "delete_messages", "Optional recent-message cleanup windows from 15 minutes to 7 days."),
        ],
        workflow=[
            "Resolves the ban duration; no duration means permanent.",
            "Validates target hierarchy and selected rule.",
            "When delete_messages is set, deletes recent logged messages from the target user and links them as deleted-message evidence.",
            "Creates the moderation action with Discord ban effects enabled.",
            "Posts public notice and an ephemeral moderator receipt.",
        ],
        notes=[
            "Commands support recent target-user cleanup. The dashboard additionally supports selecting specific logged messages.",
        ],
    ),
    BotCommandDocModel(
        id="mod.unban",
        name="unban",
        qualified_name="mod unban",
        invoke="/mod unban",
        category="moderation-actions",
        summary="Unban a Discord user and close active ban actions.",
        required_permissions=["ban_members"],
        parameters=[_param("user", "user", "Banned Discord user."), _param("reason", "string", "Optional unban reason.", required=False)],
        workflow=[
            "Attempts the Discord unban.",
            "Deactivates active ban actions for the user.",
            "Posts public notice and an ephemeral moderator receipt.",
        ],
    ),
    BotCommandDocModel(
        id="mod.rules.rule_add",
        name="rule_add",
        qualified_name="mod rules rule_add",
        invoke="/mod rules rule_add",
        category="moderation-rules",
        summary="Create one moderation rule manually.",
        required_permissions=["manage_guild"],
        parameters=[
            _param("title", "string", "Rule title."),
            _param("description", "string", "Optional rule description.", required=False),
            _param("code", "string", "Optional short rule code."),
            _param("sort_order", "integer", "Ordering position from 0 to 999.", required=False, default="0"),
        ],
        workflow=["Creates the rule, commits it, refreshes the bot's in-memory rule cache, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.rules.rules_import_message",
        name="rules_import_message",
        qualified_name="mod rules rules_import_message",
        invoke="/mod rules rules_import_message",
        category="moderation-rules",
        summary="Import moderation rules from one Discord message link.",
        required_permissions=["manage_guild"],
        parameters=[
            _param("message_link", "string", "Discord message link from the same server."),
            _param("replace_existing", "boolean", "Whether to replace existing imported rules.", required=False, default="true"),
        ],
        workflow=[
            "Parses and validates the Discord message link belongs to the current server.",
            "Imports parseable rules from the message, commits them, refreshes the bot rule cache, and confirms ephemerally.",
        ],
    ),
    BotCommandDocModel(
        id="mod.rules.rules_import_messages",
        name="rules_import_messages",
        qualified_name="mod rules rules_import_messages",
        invoke="/mod rules rules_import_messages",
        category="moderation-rules",
        summary="Import moderation rules from up to 25 Discord message links.",
        required_permissions=["manage_guild"],
        parameters=[
            _param("message_links", "string", "Space, comma, or newline separated Discord message links from this server."),
            _param("replace_existing", "boolean", "Whether to replace existing imported rules.", required=False, default="true"),
        ],
        workflow=["Validates every link, imports all referenced messages, refreshes the bot rule cache, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.rules.rules_list",
        name="rules_list",
        qualified_name="mod rules rules_list",
        invoke="/mod rules rules_list",
        category="moderation-rules",
        summary="Show active moderation rules configured for the server.",
        required_permissions=["manage_guild"],
        workflow=["Loads active rules, formats them as an ephemeral list, and truncates very long output to fit Discord limits."],
    ),
    BotCommandDocModel(
        id="mod.rules.rules_parse_guide",
        name="rules_parse_guide",
        qualified_name="mod rules rules_parse_guide",
        invoke="/mod rules rules_parse_guide",
        category="moderation-rules",
        summary="Show the formatting guide for parseable moderation rules.",
        required_permissions=["manage_guild"],
        workflow=["Fetches the localized parse guide and sends guidance plus an example in an ephemeral message."],
    ),
    BotCommandDocModel(
        id="context.import_rules_from_message",
        name="Import Rules From Message",
        qualified_name="Import Rules From Message",
        invoke="Message context menu: Import Rules From Message",
        category="moderation-rules",
        discord_type="message_context_menu",
        summary="Import moderation rules from the selected Discord message.",
        required_permissions=["manage_guild"],
        workflow=["Available from a Discord message context menu.", "Imports rules without replacing existing rules and refreshes the bot rule cache."],
    ),
    BotCommandDocModel(
        id="mod.security.security_set_verified_role",
        name="security_set_verified_role",
        qualified_name="mod security security_set_verified_role",
        invoke="/mod security security_set_verified_role",
        category="security",
        summary="Set the role granted to members who finished onboarding.",
        required_permissions=["manage_guild"],
        parameters=[_param("role", "role", "Verified/member role.")],
        workflow=["Stores the verified role and captures its permissions as the normal permissions template when none exists."],
    ),
    BotCommandDocModel(
        id="mod.security.newcomer_role_suggest",
        name="newcomer_role_suggest",
        qualified_name="mod security newcomer_role_suggest",
        invoke="/mod security newcomer_role_suggest",
        category="security",
        summary="Show recommended restricted newcomer role settings.",
        required_permissions=["manage_guild"],
        workflow=["Builds the backend recommendation and sends role name, permissions, color, and rationale ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.security.security_set_newcomer_role",
        name="security_set_newcomer_role",
        qualified_name="mod security security_set_newcomer_role",
        invoke="/mod security security_set_newcomer_role",
        category="security",
        summary="Attach an existing role as the restricted newcomer role.",
        required_permissions=["manage_guild"],
        parameters=[
            _param("role", "role", "Restricted newcomer role."),
            _param("enabled", "boolean", "Enable newcomer restriction.", required=False, default="true"),
            _param("manual_release", "boolean", "Require manual release instead of timed auto-release.", required=False, default="false"),
            _param("auto_release_minutes", "integer", "Auto-release delay from 1 to 43200 minutes.", required=False),
        ],
        workflow=["Updates newcomer role settings and confirms the enabled state and release mode ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.security.security_create_newcomer_role",
        name="security_create_newcomer_role",
        qualified_name="mod security security_create_newcomer_role",
        invoke="/mod security security_create_newcomer_role",
        category="security",
        summary="Create and attach a restricted newcomer role.",
        required_permissions=["manage_roles"],
        parameters=[
            _param("role_name", "string", "Role name.", required=False, default="Newcomer"),
            _param("enabled", "boolean", "Enable newcomer restriction.", required=False, default="true"),
            _param("manual_release", "boolean", "Require manual release instead of timed auto-release.", required=False, default="true"),
            _param("auto_release_minutes", "integer", "Auto-release delay from 1 to 43200 minutes.", required=False),
            _param("mentionable", "boolean", "Whether the role is mentionable.", required=False, default="false"),
            _param("hoist", "boolean", "Whether the role displays separately.", required=False, default="false"),
            _param("color_hex", "string", "Six digit role color.", required=False, default="F2C94C"),
            _param("permissions", "string", "Discord permissions integer as a string.", required=False, default="0"),
        ],
        workflow=["Creates the role in Discord, stores it in security settings, and confirms the release mode ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.security.security_capture_permissions",
        name="security_capture_permissions",
        qualified_name="mod security security_capture_permissions",
        invoke="/mod security security_capture_permissions",
        category="security",
        summary="Capture current verified-role permissions as the normal or lockdown template.",
        required_permissions=["manage_guild"],
        parameters=[_param("mode", "choice", "Template to update.", choices=[_choice("normal"), _choice("lockdown")])],
        components=[_component("choices", "mode", "normal or lockdown.")],
        workflow=["Reads current verified role permissions and saves them into the selected template."],
    ),
    BotCommandDocModel(
        id="mod.security.security_lockdown",
        name="security_lockdown",
        qualified_name="mod security security_lockdown",
        invoke="/mod security security_lockdown",
        category="security",
        summary="Enable or disable lockdown permissions for the verified role.",
        required_permissions=["manage_guild"],
        parameters=[_param("enabled", "boolean", "Enable lockdown when true; restore normal permissions when false.")],
        workflow=["Requires a verified role and saved permission template, edits the role permissions, stores state, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.security.verify_member",
        name="verify_member",
        qualified_name="mod security verify_member",
        invoke="/mod security verify_member",
        category="security",
        summary="Grant the configured verified role to a member.",
        required_permissions=["manage_roles"],
        parameters=[USER_PARAM],
        workflow=["Checks the verified role exists, skips users that already have it, and applies the role in Discord."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_settings",
        name="moderation_settings",
        qualified_name="mod settings moderation_settings",
        invoke="/mod settings moderation_settings",
        category="moderation-settings",
        summary="Show moderation settings for this server.",
        required_permissions=["manage_roles"],
        workflow=["Loads or creates moderation settings and sends mute role, log channel, locale, and mute duration defaults ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_set_language",
        name="moderation_set_language",
        qualified_name="mod settings moderation_set_language",
        invoke="/mod settings moderation_set_language",
        category="moderation-settings",
        summary="Set the bot language for this server.",
        required_permissions=["manage_guild"],
        parameters=[_param("language", "choice", "Locale code.", choices=[_choice("English", "en"), _choice("Russian", "ru")])],
        components=[_component("choices", "language", "English or Russian.")],
        workflow=["Validates the locale is supported, updates localization settings, and confirms in the new locale."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_set_mute_role",
        name="moderation_set_mute_role",
        qualified_name="mod settings moderation_set_mute_role",
        invoke="/mod settings moderation_set_mute_role",
        category="moderation-settings",
        summary="Set the existing role to use for mutes.",
        required_permissions=["manage_roles"],
        parameters=[_param("role", "role", "Role to add during mutes and remove during unmutes.")],
        workflow=["Updates moderation settings with the role ID and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_set_log_channel",
        name="moderation_set_log_channel",
        qualified_name="mod settings moderation_set_log_channel",
        invoke="/mod settings moderation_set_log_channel",
        category="moderation-settings",
        summary="Set the moderation log channel.",
        required_permissions=["manage_guild"],
        parameters=[_param("channel", "text_channel", "Channel used for moderation log messages.")],
        workflow=["Stores the log channel ID and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_clear_log_channel",
        name="moderation_clear_log_channel",
        qualified_name="mod settings moderation_clear_log_channel",
        invoke="/mod settings moderation_clear_log_channel",
        category="moderation-settings",
        summary="Clear the moderation log channel setting.",
        required_permissions=["manage_guild"],
        workflow=["Clears the stored mod log channel and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_create_mute_role",
        name="moderation_create_mute_role",
        qualified_name="mod settings moderation_create_mute_role",
        invoke="/mod settings moderation_create_mute_role",
        category="moderation-settings",
        summary="Create a new mute role and attach it to moderation settings.",
        required_permissions=["manage_roles"],
        parameters=[_param("role_name", "string", "Role name.", required=False, default="Muted")],
        workflow=["Creates a no-permissions role, applies deny overwrites across supported channels, stores it, and reports edited/failed channels."],
    ),
    BotCommandDocModel(
        id="mod.settings.moderation_set_mute_defaults",
        name="moderation_set_mute_defaults",
        qualified_name="mod settings moderation_set_mute_defaults",
        invoke="/mod settings moderation_set_mute_defaults",
        category="moderation-settings",
        summary="Set default and maximum mute durations.",
        required_permissions=["manage_roles"],
        parameters=[
            _param("default_minutes", "integer", "Default mute length from 1 to 43200 minutes."),
            _param("max_minutes", "integer", "Maximum mute length from 1 to 43200 minutes.", required=False, default="10080"),
            _param("auto_reconnect_on_mute", "boolean", "Whether voice reconnection is automatic after mute.", required=False, default="true"),
        ],
        workflow=["Rejects defaults greater than maximum, stores settings, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.cases.create",
        name="create",
        qualified_name="mod cases create",
        invoke="/mod cases create",
        category="moderation-cases",
        summary="Open a moderation case for a user.",
        required_permissions=["moderate_members"],
        parameters=[
            USER_PARAM,
            _param("title", "string", "Case title."),
            _param("summary", "string", "Optional case summary.", required=False),
            _param("rule", "string", "Optional active rule citation.", required=False, autocomplete=True),
        ],
        components=[_component("autocomplete", "rule", "Searches active server moderation rules.")],
        workflow=["Ensures server/user records exist, optionally validates a rule, creates the case, and confirms the short case ID."],
    ),
    BotCommandDocModel(
        id="mod.cases.list",
        name="list",
        qualified_name="mod cases list",
        invoke="/mod cases list",
        category="moderation-cases",
        summary="List open moderation cases.",
        required_permissions=["moderate_members"],
        parameters=[
            _param("user", "member", "Optional target member filter.", required=False),
            _param("limit", "integer", "Maximum number of cases from 1 to 10.", required=False, default="5"),
        ],
        workflow=["Loads open cases, enriches them with details and linked actions, and sends an ephemeral embed."],
    ),
    BotCommandDocModel(
        id="mod.cases.show",
        name="show",
        qualified_name="mod cases show",
        invoke="/mod cases show",
        category="moderation-cases",
        summary="Show moderation case details.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM],
        components=[_component("button", "Open case", "Link button to the case in the dashboard.")],
        workflow=["Loads case details, sends an embed with target, status, notes, evidence, rules, and linked actions, plus a dashboard button."],
    ),
    BotCommandDocModel(
        id="mod.cases.close",
        name="close",
        qualified_name="mod cases close",
        invoke="/mod cases close",
        category="moderation-cases",
        summary="Close a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM],
        workflow=["Sets case status to closed and records the closing moderator."],
    ),
    BotCommandDocModel(
        id="mod.cases.reopen",
        name="reopen",
        qualified_name="mod cases reopen",
        invoke="/mod cases reopen",
        category="moderation-cases",
        summary="Reopen a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM],
        workflow=["Sets case status back to open."],
    ),
    BotCommandDocModel(
        id="mod.cases.archive",
        name="archive",
        qualified_name="mod cases archive",
        invoke="/mod cases archive",
        category="moderation-cases",
        summary="Archive a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM],
        workflow=["Sets case status to archived and records the acting moderator."],
    ),
    BotCommandDocModel(
        id="mod.cases.note",
        name="note",
        qualified_name="mod cases note",
        invoke="/mod cases note",
        category="moderation-cases",
        summary="Add a note to a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[
            CASE_ID_PARAM,
            _param("note", "string", "Note text."),
            _param("internal", "boolean", "Whether the note is internal.", required=False, default="true"),
        ],
        workflow=["Creates the case note as the invoking moderator and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.cases.evidence",
        name="evidence",
        qualified_name="mod cases evidence",
        invoke="/mod cases evidence",
        category="moderation-cases",
        summary="Add text or URL evidence to a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[
            CASE_ID_PARAM,
            _param("evidence_type", "choice", "Evidence type.", choices=[_choice("URL", "link"), _choice("Text", "text")]),
            _param("value", "string", "URL or text evidence value."),
        ],
        components=[_component("choices", "evidence_type", "URL or Text.")],
        workflow=["Maps URL to link evidence and Text to note evidence, stores it, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.cases.add_user",
        name="add_user",
        qualified_name="mod cases add_user",
        invoke="/mod cases add_user",
        category="moderation-cases",
        summary="Add a related user or target user to a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[
            CASE_ID_PARAM,
            USER_PARAM,
            _param("role", "choice", "Case relationship role.", choices=[_choice("Related", "related"), _choice("Target", "target")]),
        ],
        components=[_component("choices", "role", "Related or Target.")],
        workflow=["Adds the user relationship to the case and confirms the role used."],
    ),
    BotCommandDocModel(
        id="mod.cases.remove_user",
        name="remove_user",
        qualified_name="mod cases remove_user",
        invoke="/mod cases remove_user",
        category="moderation-cases",
        summary="Remove a related user from a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM, USER_PARAM],
        workflow=["Removes the user relationship from the case and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.cases.add_rule",
        name="add_rule",
        qualified_name="mod cases add_rule",
        invoke="/mod cases add_rule",
        category="moderation-cases",
        summary="Add a rule citation to a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM, RULE_PARAM],
        components=[_component("autocomplete", "rule", "Searches active server moderation rules.")],
        workflow=["Validates the selected rule and links it to the case."],
    ),
    BotCommandDocModel(
        id="mod.cases.remove_rule",
        name="remove_rule",
        qualified_name="mod cases remove_rule",
        invoke="/mod cases remove_rule",
        category="moderation-cases",
        summary="Remove a rule citation from a moderation case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM, _param("rule", "string", "Rule UUID selected from autocomplete.", autocomplete=True)],
        components=[_component("autocomplete", "rule", "Searches active server moderation rules.")],
        workflow=["Removes the rule link from the case and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.cases.link_action",
        name="link_action",
        qualified_name="mod cases link_action",
        invoke="/mod cases link_action",
        category="moderation-cases",
        summary="Link an existing moderation action to a case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM, ACTION_ID_PARAM],
        workflow=["Links the action UUID to the case and records the invoking moderator."],
    ),
    BotCommandDocModel(
        id="mod.cases.unlink_action",
        name="unlink_action",
        qualified_name="mod cases unlink_action",
        invoke="/mod cases unlink_action",
        category="moderation-cases",
        summary="Unlink a moderation action from a case.",
        required_permissions=["moderate_members"],
        parameters=[CASE_ID_PARAM, ACTION_ID_PARAM],
        workflow=["Removes the action link from the case and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="mod.actions.list",
        name="list",
        qualified_name="mod actions list",
        invoke="/mod actions list",
        category="moderation-actions",
        summary="List recent moderation actions.",
        required_permissions=["moderate_members"],
        parameters=[
            _param("user", "member", "Optional target member filter.", required=False),
            _param("limit", "integer", "Maximum number of actions from 1 to 10.", required=False, default="5"),
        ],
        workflow=["Loads recent action summaries and sends an ephemeral embed with dashboard links."],
    ),
    BotCommandDocModel(
        id="mod.actions.manage",
        name="manage",
        qualified_name="mod actions manage",
        invoke="/mod actions manage",
        category="moderation-actions",
        summary="Show action controls for a moderation action.",
        required_permissions=["moderate_members"],
        parameters=[ACTION_ID_PARAM],
        components=[
            _component("button", "Open dashboard", "Link button to the moderation action in the dashboard."),
            _component("button", "Add info in dashboard", "Second dashboard link button for adding details."),
            _component("dashboard", "Delete messages", "Dashboard action form can delete selected or recent target-user messages and attach them to the action."),
            _component("button", "Revert", "Danger button enabled for active mute and ban actions."),
        ],
        workflow=[
            "Loads action details, sends an action embed, and displays dashboard links plus a conditional revert button.",
            "Deleted-message evidence is managed in the dashboard, including linking existing deleted messages and cleanup performed while applying an action.",
        ],
    ),
    BotCommandDocModel(
        id="mod.actions.revert",
        name="revert",
        qualified_name="mod actions revert",
        invoke="/mod actions revert",
        category="moderation-actions",
        summary="Revert an active mute or ban action.",
        required_permissions=["moderate_members"],
        parameters=[ACTION_ID_PARAM, _param("reason", "string", "Optional revert reason.", required=False)],
        workflow=["Fetches the action, only permits active mutes and bans, applies the Discord reversal, deactivates the action, logs it, and confirms."],
    ),
    BotCommandDocModel(
        id="add_my_birthday",
        name="add_my_birthday",
        qualified_name="add_my_birthday",
        invoke="/add_my_birthday",
        category="birthdays",
        summary="Add your birthday to the server birthday list.",
        parameters=[
            _param("day", "integer", "Day of month."),
            _param("month", "choice", "Month.", choices=[_choice(str(month).zfill(2), str(month).zfill(2)) for month in range(1, 13)]),
        ],
        components=[_component("choices", "month", "Twelve month choices.")],
        workflow=["Passes the selected day/month to the birthday module for validation and storage."],
    ),
    BotCommandDocModel(
        id="birthdays_settings",
        name="birthdays_settings",
        qualified_name="birthdays_settings",
        invoke="/birthdays_settings",
        category="birthdays",
        summary="Configure the server birthday channel and birthday role through Discord UI controls.",
        components=[
            _component("button", "Select existing", "Starts a channel select flow."),
            _component("button", "Create default", "Creates the default birthday text channel."),
            _component("select", "Birthday channel", "Discord channel select for the birthday announcement channel."),
            _component("select", "Birthday role", "Discord role select for the role granted to birthday users."),
        ],
        workflow=["Shows current settings when configured, or launches a channel and role selection flow when not configured."],
    ),
    BotCommandDocModel(
        id="add_reply",
        name="add_reply",
        qualified_name="add_reply",
        invoke="/add_reply",
        category="replies",
        summary="Add a custom bot reply trigger for the current server.",
        parameters=[_param("phrase", "string", "Trigger phrase."), _param("response", "string", "Bot response text.")],
        workflow=["Normalizes the trigger phrase, creates a reply and trigger row, and confirms ephemerally."],
    ),
    BotCommandDocModel(
        id="delete_reply",
        name="delete_reply",
        qualified_name="delete_reply",
        invoke="/delete_reply",
        category="replies",
        summary="Delete a custom bot reply trigger.",
        parameters=[_param("trigger", "string", "Trigger search text.", autocomplete=True)],
        components=[
            _component("autocomplete", "trigger", "Searches configured reply triggers."),
            _component("select", "Matching triggers", "When multiple triggers match, lets the user pick one."),
            _component("button", "Delete", "Confirms deletion."),
            _component("button", "Cancel", "Leaves the reply unchanged."),
            _component("button", "Back to list", "Returns from confirmation to the matching-trigger select."),
        ],
        workflow=["Searches triggers, shows direct confirmation for one match or a select menu for multiple matches, then deletes the trigger and orphaned reply when confirmed."],
    ),
    BotCommandDocModel(
        id="check_dr",
        name="check_dr",
        qualified_name="check_dr",
        invoke="/check_dr",
        category="birthdays",
        summary="Force a birthday role check.",
        workflow=["Runs birthday and role checks immediately, then responds OK."],
        notes=["Primarily an operational/testing command."],
    ),
    BotCommandDocModel(
        id="birthday_list",
        name="birthday_list",
        qualified_name="birthday_list",
        invoke="/birthday_list",
        category="birthdays",
        summary="Show all birthdays on the server.",
        workflow=["Delegates to the birthday list module with page size 15."],
    ),
    BotCommandDocModel(
        id="show_replies",
        name="show_replies",
        qualified_name="show_replies",
        invoke="/show_replies",
        category="replies",
        summary="Show all configured custom reply triggers for the server.",
        components=[_component("pagination", "Replies list", "Paginated Discord view when replies exist.")],
        workflow=["Loads triggers and replies for the server, then displays them through the pagination view."],
    ),
    BotCommandDocModel(
        id="force_validation",
        name="force_validation",
        qualified_name="force_validation",
        invoke="/force_validation",
        category="maintenance",
        summary="Force user validation.",
        workflow=["Runs the validation process and reports success or the exception ephemerally."],
        notes=["The command description marks this as testing-purpose functionality."],
    ),
    BotCommandDocModel(
        id="cat_text",
        name="cat_text",
        qualified_name="cat_text",
        invoke="/cat_text",
        category="misc",
        summary="Send a generated cat image with text.",
        parameters=[_param("text", "string", "Text to render on the cat image.")],
        workflow=["Fetches an image from cataas.com, sends it as cat.png, and deletes the temporary local file."],
    ),
    BotCommandDocModel(
        id="cat",
        name="cat",
        qualified_name="cat",
        invoke="/cat",
        category="misc",
        summary="Send a generated cat image.",
        workflow=["Fetches an image from cataas.com, sends it as cat.png, and deletes the temporary local file."],
    ),
)

COMMAND_RBAC_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "mod.warn": ("moderation.actions.apply.warn",),
    "mod.mute": ("moderation.actions.apply.mute",),
    "mod.unmute": ("moderation.actions.apply.mute",),
    "mod.kick": ("moderation.actions.apply.kick",),
    "mod.ban": ("moderation.actions.apply.ban",),
    "mod.unban": ("moderation.actions.apply.ban",),
    "mod.rules.rule_add": ("moderation.rules.manage",),
    "mod.rules.rules_import_message": ("moderation.rules.manage",),
    "mod.rules.rules_import_messages": ("moderation.rules.manage",),
    "mod.rules.rules_list": ("moderation.rules.view",),
    "mod.rules.rules_parse_guide": ("moderation.rules.view",),
    "context.import_rules_from_message": ("moderation.rules.manage",),
    "mod.security.security_set_verified_role": ("security.settings.edit",),
    "mod.security.newcomer_role_suggest": ("security.settings.edit",),
    "mod.security.security_set_newcomer_role": ("security.settings.edit",),
    "mod.security.security_create_newcomer_role": ("security.settings.edit",),
    "mod.security.security_capture_permissions": ("security.settings.edit",),
    "mod.security.security_lockdown": ("security.lockdown.manage",),
    "mod.security.verify_member": ("security.settings.edit",),
    "mod.settings.moderation_settings": ("moderation.settings.view",),
    "mod.settings.moderation_set_language": ("localization.settings.edit",),
    "mod.settings.moderation_set_mute_role": ("moderation.settings.edit",),
    "mod.settings.moderation_set_log_channel": ("moderation.settings.edit",),
    "mod.settings.moderation_clear_log_channel": ("moderation.settings.edit",),
    "mod.settings.moderation_create_mute_role": ("moderation.settings.edit",),
    "mod.settings.moderation_set_mute_defaults": ("moderation.settings.edit",),
    "mod.cases.create": ("moderation.cases.manage",),
    "mod.cases.list": ("moderation.cases.view",),
    "mod.cases.show": ("moderation.cases.view",),
    "mod.cases.close": ("moderation.cases.manage",),
    "mod.cases.reopen": ("moderation.cases.manage",),
    "mod.cases.archive": ("moderation.cases.manage",),
    "mod.cases.note": ("moderation.cases.manage",),
    "mod.cases.evidence": ("moderation.cases.manage",),
    "mod.cases.add_user": ("moderation.cases.manage",),
    "mod.cases.remove_user": ("moderation.cases.manage",),
    "mod.cases.add_rule": ("moderation.cases.manage",),
    "mod.cases.remove_rule": ("moderation.cases.manage",),
    "mod.cases.link_action": ("moderation.cases.manage",),
    "mod.cases.unlink_action": ("moderation.cases.manage",),
    "mod.actions.list": ("moderation.actions.view",),
    "mod.actions.manage": ("moderation.actions.view",),
    "mod.actions.revert": ("moderation.actions.revert",),
}


def _with_rbac_permissions(command: BotCommandDocModel) -> BotCommandDocModel:
    permission_keys = COMMAND_RBAC_PERMISSIONS.get(command.id, ())
    if not permission_keys:
        return command
    return command.model_copy(update={"required_rbac_permissions": list(permission_keys)})


BOT_COMMANDS = tuple(_with_rbac_permissions(command) for command in BOT_COMMANDS)
COMMANDS_BY_ID: dict[str, BotCommandDocModel] = {command.id: command for command in BOT_COMMANDS}
AVAILABLE_BOT_COMMAND_LOCALES: tuple[str, ...] = ("en", "ru")

RU_PARAMETER_DESCRIPTIONS: dict[str, str] = {
    "action_id": "UUID модераторского действия.",
    "auto_reconnect_on_mute": "Нужно ли автоматически возвращать пользователя в голосовой канал после мута.",
    "auto_release_minutes": "Задержка автоматического снятия ограничений от 1 до 43200 минут.",
    "case": "UUID модераторского дела или вариант из автодополнения.",
    "channel": "Канал Discord.",
    "code": "Необязательный короткий код правила.",
    "color_hex": "Цвет роли в формате из шести hex-символов.",
    "commentary": "Необязательный комментарий модератора, который сохранится вместе с действием.",
    "default_minutes": "Длительность мута по умолчанию от 1 до 43200 минут.",
    "description": "Необязательное описание.",
    "duration": "Готовый вариант длительности.",
    "duration_unit": "Единица измерения для duration_value.",
    "duration_value": "Свое значение длительности от 1 до 999.",
    "enabled": "Включить или отключить настройку.",
    "evidence_type": "Тип доказательства.",
    "hoist": "Показывать роль отдельно в списке участников.",
    "internal": "Считать заметку внутренней.",
    "language": "Язык бота для этого сервера.",
    "limit": "Максимальное количество элементов в выдаче.",
    "manual_release": "Требовать ручное снятие ограничений вместо таймера.",
    "max_minutes": "Максимальная длительность мута от 1 до 43200 минут.",
    "mentionable": "Можно ли упоминать роль.",
    "message_link": "Ссылка на сообщение Discord с этого сервера.",
    "message_links": "Ссылки на сообщения Discord через пробел, запятую или новую строку.",
    "mode": "Какой шаблон прав обновить.",
    "month": "Месяц.",
    "permissions": "Целое число прав Discord в виде строки.",
    "phrase": "Фраза-триггер.",
    "reason": "Необязательная причина.",
    "replace_existing": "Заменить ли уже импортированные правила.",
    "response": "Текст ответа бота.",
    "role": "Роль Discord.",
    "role_name": "Название роли.",
    "rule": "Правило сервера из активных правил.",
    "sort_order": "Позиция сортировки от 0 до 999.",
    "summary": "Необязательное краткое описание дела.",
    "text": "Текст для изображения.",
    "title": "Название.",
    "trigger": "Текст для поиска триггера.",
    "user": "Пользователь Discord.",
    "value": "Значение: ссылка или текст.",
}

RU_CHOICE_NAMES_BY_VALUE: dict[str, str] = {
    "default": "настройка сервера",
    "permanent": "навсегда",
    "10m": "10 минут",
    "30m": "30 минут",
    "1h": "1 час",
    "6h": "6 часов",
    "12h": "12 часов",
    "1d": "1 день",
    "3d": "3 дня",
    "1w": "1 неделя",
    "2w": "2 недели",
    "30d": "30 дней",
    "minutes": "минуты",
    "hours": "часы",
    "days": "дни",
    "weeks": "недели",
    "months": "месяцы",
    "normal": "обычный",
    "lockdown": "локдаун",
    "en": "Английский",
    "ru": "Русский",
    "link": "URL",
    "text": "Текст",
    "related": "Связанный",
    "target": "Цель",
}

RU_COMPONENTS_BY_LABEL: dict[str, tuple[str, str]] = {
    "Add info in dashboard": ("Добавить информацию", "Кнопка-ссылка для добавления деталей в панели управления."),
    "Back to list": ("Назад к списку", "Возвращает от подтверждения к списку найденных триггеров."),
    "Birthday channel": ("Канал дней рождения", "Выбор канала Discord для поздравлений."),
    "Birthday role": ("Роль дня рождения", "Выбор роли Discord, которую бот выдает именинникам."),
    "Create default": ("Создать стандартный", "Создает стандартный текстовый канал для дней рождения."),
    "Delete": ("Удалить", "Подтверждает удаление."),
    "Delete messages": (
        "Удалить сообщения",
        "Опция панели управления: удаляет выбранные или недавние сообщения цели и привязывает их к действию.",
    ),
    "Cancel": ("Отмена", "Оставляет запись без изменений."),
    "Matching triggers": ("Найденные триггеры", "Если совпадений несколько, позволяет выбрать нужный триггер."),
    "Open case": ("Открыть дело", "Кнопка-ссылка на дело в панели управления."),
    "Open dashboard": ("Открыть в панели", "Кнопка-ссылка на модераторское действие в панели управления."),
    "Replies list": ("Список ответов", "Постраничный список Discord, когда ответы настроены."),
    "Revert": ("Откатить", "Опасная кнопка, доступная для активных мутов и банов."),
    "Select existing": ("Выбрать существующий", "Запускает выбор существующего канала."),
    "case": ("Дело", "Автодополнение предлагает подходящие модераторские дела."),
    "duration": ("Длительность", "Готовые варианты длительности."),
    "duration_unit": ("Единица длительности", "Минуты, часы, дни, недели или месяцы."),
    "evidence_type": ("Тип доказательства", "URL или текст."),
    "language": ("Язык", "Английский или русский."),
    "mode": ("Режим", "Обычный шаблон или шаблон локдауна."),
    "month": ("Месяц", "Двенадцать вариантов месяца."),
    "role": ("Роль", "Связь пользователя с делом: связанный или цель."),
    "rule": ("Правило", "Автодополнение ищет активные правила сервера."),
    "trigger": ("Триггер", "Автодополнение ищет настроенные триггеры ответов."),
}

RU_COMMAND_TEXT: dict[str, dict[str, list[str] | str]] = {
    "mod.warn": {
        "summary": "Выдать предупреждение участнику, указать правило сервера и записать модераторское действие.",
        "workflow": [
            "Проверяет, что команда запущена на сервере.",
            "Загружает активные правила сервера и требует корректное выбранное правило.",
            "Проверяет, что модератор может применить действие к выбранному участнику.",
            "Создает или связывает модераторское дело, создает предупреждение и сохраняет изменения.",
            "Публикует уведомление в канале и отправляет модератору приватный отчет.",
        ],
    },
    "mod.mute": {
        "summary": "Выдать настроенную mute-роль на выбранную длительность и записать действие.",
        "workflow": [
            "Загружает настройки модерации и требует настроенную mute-роль.",
            "Проверяет, что роль существует и находится ниже роли бота.",
            "Вычисляет длительность по готовому варианту или пользовательским полям.",
            "Записывает мут, применяет изменения в Discord, публикует уведомление и отправляет приватный отчет.",
        ],
    },
    "mod.unmute": {
        "summary": "Снять mute-роль и закрыть активные муты участника.",
        "workflow": [
            "Проверяет выбранного участника.",
            "Снимает настроенную mute-роль, если она есть у пользователя.",
            "Деактивирует активные mute-действия пользователя.",
            "Пишет в модераторский лог при настроенном канале, публикует уведомление и отправляет приватный отчет.",
        ],
    },
    "mod.kick": {
        "summary": "Кикнуть участника и записать действие со ссылкой на правило.",
        "workflow": [
            "Проверяет иерархию ролей и выбранное правило.",
            "Создает модераторское действие через общий сервис и применяет Discord-эффект.",
            "Публикует уведомление и отправляет модератору приватный отчет.",
        ],
    },
    "mod.ban": {
        "summary": "Забанить участника навсегда или на выбранный срок и записать действие.",
        "workflow": [
            "Вычисляет длительность бана; без выбранной длительности бан считается постоянным.",
            "Проверяет иерархию ролей и выбранное правило.",
            "Создает модераторское действие и применяет бан в Discord.",
            "Публикует уведомление и отправляет модератору приватный отчет.",
        ],
    },
    "mod.unban": {
        "summary": "Разбанить пользователя Discord и закрыть активные ban-действия.",
        "workflow": [
            "Пытается снять бан в Discord.",
            "Деактивирует активные ban-действия пользователя.",
            "Публикует уведомление и отправляет модератору приватный отчет.",
        ],
    },
    "mod.rules.rule_add": {
        "summary": "Создать одно правило модерации вручную.",
        "workflow": ["Создает правило, сохраняет его, обновляет кеш правил бота и подтверждает действие приватным сообщением."],
    },
    "mod.rules.rules_import_message": {
        "summary": "Импортировать правила модерации из одной ссылки на сообщение Discord.",
        "workflow": [
            "Разбирает ссылку и проверяет, что сообщение относится к текущему серверу.",
            "Импортирует распознаваемые правила из сообщения, сохраняет их, обновляет кеш правил и подтверждает приватно.",
        ],
    },
    "mod.rules.rules_import_messages": {
        "summary": "Импортировать правила модерации из нескольких ссылок на сообщения Discord, максимум 25.",
        "workflow": ["Проверяет каждую ссылку, импортирует все указанные сообщения, обновляет кеш правил и подтверждает приватно."],
    },
    "mod.rules.rules_list": {
        "summary": "Показать активные правила модерации, настроенные на сервере.",
        "workflow": ["Загружает активные правила, форматирует приватный список и обрезает слишком длинный текст под лимиты Discord."],
    },
    "mod.rules.rules_parse_guide": {
        "summary": "Показать инструкцию по формату правил, которые можно импортировать автоматически.",
        "workflow": ["Загружает локализованную инструкцию и отправляет советы вместе с примером приватным сообщением."],
    },
    "context.import_rules_from_message": {
        "summary": "Импортировать правила модерации из выбранного сообщения Discord.",
        "workflow": ["Доступно через контекстное меню сообщения Discord.", "Импортирует правила без замены существующих и обновляет кеш правил бота."],
    },
    "mod.security.security_set_verified_role": {
        "summary": "Установить роль, которую получают участники после прохождения онбординга.",
        "workflow": ["Сохраняет verified-роль и, если обычный шаблон прав еще не задан, снимает с нее текущие права как шаблон normal."],
    },
    "mod.security.newcomer_role_suggest": {
        "summary": "Показать рекомендуемые настройки ограниченной роли новичка.",
        "workflow": ["Строит рекомендацию на backend и отправляет название роли, права, цвет и объяснение приватным сообщением."],
    },
    "mod.security.security_set_newcomer_role": {
        "summary": "Назначить существующую роль как ограниченную роль новичка.",
        "workflow": ["Обновляет настройки роли новичка и приватно подтверждает состояние включения и режим снятия ограничений."],
    },
    "mod.security.security_create_newcomer_role": {
        "summary": "Создать и привязать ограниченную роль новичка.",
        "workflow": ["Создает роль в Discord, сохраняет ее в настройках безопасности и приватно подтверждает режим снятия ограничений."],
    },
    "mod.security.security_capture_permissions": {
        "summary": "Сохранить текущие права verified-роли как обычный шаблон или шаблон локдауна.",
        "workflow": ["Читает текущие права verified-роли и сохраняет их в выбранный шаблон."],
    },
    "mod.security.security_lockdown": {
        "summary": "Включить или отключить lockdown-права для verified-роли.",
        "workflow": ["Требует verified-роль и сохраненный шаблон прав, меняет права роли, сохраняет состояние и подтверждает приватно."],
    },
    "mod.security.verify_member": {
        "summary": "Выдать участнику настроенную verified-роль.",
        "workflow": ["Проверяет, что роль настроена, пропускает пользователей, у которых она уже есть, и выдает роль в Discord."],
    },
    "mod.settings.moderation_settings": {
        "summary": "Показать настройки модерации этого сервера.",
        "workflow": ["Загружает или создает настройки модерации и приватно показывает mute-роль, канал логов, язык и длительности мута."],
    },
    "mod.settings.moderation_set_language": {
        "summary": "Установить язык бота для этого сервера.",
        "workflow": ["Проверяет, что язык поддерживается, обновляет настройки локализации и подтверждает на новом языке."],
    },
    "mod.settings.moderation_set_mute_role": {
        "summary": "Назначить существующую роль для мутов.",
        "workflow": ["Обновляет настройки модерации ID роли и подтверждает приватно."],
    },
    "mod.settings.moderation_set_log_channel": {
        "summary": "Назначить канал модераторских логов.",
        "workflow": ["Сохраняет ID канала логов и подтверждает приватно."],
    },
    "mod.settings.moderation_clear_log_channel": {
        "summary": "Очистить настройку канала модераторских логов.",
        "workflow": ["Очищает сохраненный канал модераторских логов и подтверждает приватно."],
    },
    "mod.settings.moderation_create_mute_role": {
        "summary": "Создать новую mute-роль и привязать ее к настройкам модерации.",
        "workflow": ["Создает роль без прав, применяет запреты в поддерживаемых каналах, сохраняет роль и сообщает число успешных и неуспешных изменений."],
    },
    "mod.settings.moderation_set_mute_defaults": {
        "summary": "Задать стандартную и максимальную длительность мута.",
        "workflow": ["Отклоняет значение по умолчанию больше максимума, сохраняет настройки и подтверждает приватно."],
    },
    "mod.cases.create": {
        "summary": "Открыть модераторское дело на пользователя.",
        "workflow": ["Проверяет записи сервера и пользователей, при необходимости проверяет правило, создает дело и подтверждает короткий ID."],
    },
    "mod.cases.list": {
        "summary": "Показать открытые модераторские дела.",
        "workflow": ["Загружает открытые дела, добавляет детали и связанные действия, затем отправляет приватный embed."],
    },
    "mod.cases.show": {
        "summary": "Показать детали модераторского дела.",
        "workflow": ["Загружает детали дела и отправляет embed с целью, статусом, заметками, доказательствами, правилами, связанными действиями и кнопкой панели."],
    },
    "mod.cases.close": {
        "summary": "Закрыть модераторское дело.",
        "workflow": ["Меняет статус дела на closed и записывает модератора, который закрыл дело."],
    },
    "mod.cases.reopen": {
        "summary": "Переоткрыть модераторское дело.",
        "workflow": ["Возвращает статус дела в open."],
    },
    "mod.cases.archive": {
        "summary": "Архивировать модераторское дело.",
        "workflow": ["Меняет статус дела на archived и записывает действующего модератора."],
    },
    "mod.cases.note": {
        "summary": "Добавить заметку к модераторскому делу.",
        "workflow": ["Создает заметку от имени вызвавшего модератора и подтверждает приватно."],
    },
    "mod.cases.evidence": {
        "summary": "Добавить текстовое доказательство или ссылку к модераторскому делу.",
        "workflow": ["Преобразует URL в link-доказательство, а Text в текстовую заметку, сохраняет запись и подтверждает приватно."],
    },
    "mod.cases.add_user": {
        "summary": "Добавить связанного пользователя или цель в модераторское дело.",
        "workflow": ["Добавляет связь пользователя с делом и подтверждает использованную роль."],
    },
    "mod.cases.remove_user": {
        "summary": "Удалить связанного пользователя из модераторского дела.",
        "workflow": ["Удаляет связь пользователя с делом и подтверждает приватно."],
    },
    "mod.cases.add_rule": {
        "summary": "Добавить ссылку на правило в модераторское дело.",
        "workflow": ["Проверяет выбранное правило и связывает его с делом."],
    },
    "mod.cases.remove_rule": {
        "summary": "Удалить ссылку на правило из модераторского дела.",
        "workflow": ["Удаляет связь правила с делом и подтверждает приватно."],
    },
    "mod.cases.link_action": {
        "summary": "Связать существующее модераторское действие с делом.",
        "workflow": ["Связывает UUID действия с делом и записывает вызвавшего модератора."],
    },
    "mod.cases.unlink_action": {
        "summary": "Отвязать модераторское действие от дела.",
        "workflow": ["Удаляет связь действия с делом и подтверждает приватно."],
    },
    "mod.actions.list": {
        "summary": "Показать недавние модераторские действия.",
        "workflow": ["Загружает недавние действия и отправляет приватный embed со ссылками на панель управления."],
    },
    "mod.actions.manage": {
        "summary": "Показать элементы управления модераторским действием.",
        "workflow": ["Загружает детали действия, отправляет embed и показывает ссылки на панель вместе с условной кнопкой отката."],
    },
    "mod.actions.revert": {
        "summary": "Откатить активный мут или бан.",
        "workflow": ["Находит действие, разрешает только активные муты и баны, применяет откат в Discord, деактивирует действие, логирует и подтверждает."],
    },
    "add_my_birthday": {
        "summary": "Добавить свой день рождения в список сервера.",
        "workflow": ["Передает выбранные день и месяц в модуль дней рождения для проверки и сохранения."],
    },
    "birthdays_settings": {
        "summary": "Настроить канал дней рождения и роль именинника через Discord UI.",
        "workflow": ["Показывает текущие настройки, если они есть, или запускает выбор канала и роли."],
    },
    "add_reply": {
        "summary": "Добавить пользовательский триггер ответа бота для текущего сервера.",
        "workflow": ["Нормализует фразу-триггер, создает запись ответа и триггера, затем подтверждает приватно."],
    },
    "delete_reply": {
        "summary": "Удалить пользовательский триггер ответа бота.",
        "workflow": ["Ищет триггеры, показывает подтверждение для одного совпадения или меню выбора для нескольких, затем удаляет триггер и осиротевший ответ после подтверждения."],
    },
    "check_dr": {
        "summary": "Принудительно запустить проверку ролей дней рождения.",
        "workflow": ["Сразу запускает проверки дней рождения и ролей, затем отвечает OK."],
        "notes": ["В основном служебная или тестовая команда."],
    },
    "birthday_list": {
        "summary": "Показать все дни рождения на сервере.",
        "workflow": ["Передает работу модулю списка дней рождения с размером страницы 15."],
    },
    "show_replies": {
        "summary": "Показать все настроенные триггеры пользовательских ответов на сервере.",
        "workflow": ["Загружает триггеры и ответы сервера, затем показывает их через постраничный Discord view."],
    },
    "force_validation": {
        "summary": "Принудительно запустить проверку пользователей.",
        "workflow": ["Запускает процесс валидации и приватно сообщает успех или ошибку."],
        "notes": ["Описание команды помечает ее как функциональность для тестирования."],
    },
    "cat_text": {
        "summary": "Отправить сгенерированную картинку кота с текстом.",
        "workflow": ["Загружает изображение с cataas.com, отправляет его как cat.png и удаляет временный локальный файл."],
    },
    "cat": {
        "summary": "Отправить сгенерированную картинку кота.",
        "workflow": ["Загружает изображение с cataas.com, отправляет его как cat.png и удаляет временный локальный файл."],
    },
}


def normalize_bot_command_locale(locale: str | None) -> str:
    normalized = (locale or "en").strip().lower().replace("_", "-")
    if normalized.startswith("ru"):
        return "ru"
    return "en"


def _localize_choices(choices: list[BotCommandChoiceModel], locale: str) -> list[BotCommandChoiceModel]:
    if locale != "ru":
        return choices
    return [
        choice.model_copy(update={"name": RU_CHOICE_NAMES_BY_VALUE.get(choice.value, choice.name)})
        for choice in choices
    ]


def _localize_parameters(parameters: list[BotCommandParameterModel], locale: str) -> list[BotCommandParameterModel]:
    if locale != "ru":
        return parameters
    return [
        parameter.model_copy(
            update={
                "description": RU_PARAMETER_DESCRIPTIONS.get(parameter.name, parameter.description),
                "choices": _localize_choices(parameter.choices, locale),
            }
        )
        for parameter in parameters
    ]


def _localize_components(components: list[BotCommandComponentModel], locale: str) -> list[BotCommandComponentModel]:
    if locale != "ru":
        return components
    localized: list[BotCommandComponentModel] = []
    for component in components:
        label, description = RU_COMPONENTS_BY_LABEL.get(component.label, (component.label, component.description))
        localized.append(component.model_copy(update={"label": label, "description": description}))
    return localized


def _localize_command(command: BotCommandDocModel, locale: str) -> BotCommandDocModel:
    if locale != "ru":
        return command
    translation = RU_COMMAND_TEXT.get(command.id, {})
    return command.model_copy(
        deep=True,
        update={
            "summary": translation.get("summary", command.summary),
            "parameters": _localize_parameters(command.parameters, locale),
            "components": _localize_components(command.components, locale),
            "workflow": translation.get("workflow", command.workflow),
            "notes": translation.get("notes", command.notes),
        },
    )


def list_bot_commands(
    *,
    category: str | None = None,
    discord_type: str | None = None,
    locale: str = "en",
) -> list[BotCommandDocModel]:
    resolved_locale = normalize_bot_command_locale(locale)
    commands = list(BOT_COMMANDS)
    if category:
        normalized_category = category.strip().lower()
        commands = [command for command in commands if command.category.lower() == normalized_category]
    if discord_type:
        normalized_type = discord_type.strip().lower()
        commands = [command for command in commands if command.discord_type.lower() == normalized_type]
    return [_localize_command(command, resolved_locale) for command in commands]


def get_bot_command(command_id: str, *, locale: str = "en") -> BotCommandDocModel | None:
    command = COMMANDS_BY_ID.get(command_id.strip())
    if command is None:
        return None
    return _localize_command(command, normalize_bot_command_locale(locale))
