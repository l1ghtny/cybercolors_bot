import discord
from uuid import UUID

from discord import app_commands

from api.models.moderation_cases import (
    ModerationCaseCreateModel,
    ModerationCaseEvidenceCreateModel,
    ModerationCaseNoteCreateModel,
    ModerationCaseRulesUpsertModel,
    ModerationCaseStatusUpdateModel,
)
from api.services.moderation_action_numbers import resolve_moderation_action_reference
from api.services.moderation_actions_service import (
    _dashboard_action_url,
    _dashboard_case_url,
    list_action_summaries,
)
from api.services.moderation_cases_service import (
    add_case_evidence,
    add_case_note,
    add_user_to_case,
    create_case,
    get_case_details,
    link_action_to_case,
    list_cases,
    remove_action_from_case,
    remove_case_rule,
    remove_user_from_case,
    update_case_status,
    upsert_case_rules,
)
from src.db.database import get_async_session
from src.db.models import CaseStatus, CaseUserRole, EvidenceType
from src.modules.localization.service import get_server_locale, tr
from src.modules.moderation.bot_rbac import ensure_bot_permission, has_bot_permission
from src.modules.moderation.bot_services import (
    action_choices,
    case_choices,
    fetch_active_rule_models,
    fetch_open_case_models,
    find_rule,
    rule_choices,
    rule_label,
)
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

def _truncate_discord(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _case_dashboard_link(server_id: int, case_id: str, label: str = "Open case") -> str:
    return f"[{label}]({_dashboard_case_url(server_id, case_id)})"


def _action_dashboard_link(
    server_id: int,
    action_id: str,
    action_number: int,
    action_type: object,
) -> str:
    action_label = action_type.value if hasattr(action_type, "value") else str(action_type)
    return f"[{action_label} #{action_number}]({_dashboard_action_url(server_id, action_id)})"


def _actor_line(label: str, actor) -> str:
    display = actor.display_name or actor.username or actor.user_id
    return f"{label}: <@{actor.user_id}> (`{display}`)"


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(
    name="create",
    description="Open a moderation case for a user.",
)
async def case_create(
    interaction: discord.Interaction,
    user: discord.Member,
    title: str,
    summary: str | None = None,
    rule: str | None = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    summary_text = summary.strip() if summary else None

    try:
        async with get_async_session() as session:
            await check_if_server_exists(interaction.guild, session)
            await check_if_user_exists(user, interaction.guild, session)
            await check_if_user_exists(interaction.user, interaction.guild, session)

            rule_ids: list[str] = []
            selected_rule_label = None
            if rule:
                rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
                selected_rule = find_rule(rules, rule)
                if selected_rule is None:
                    await interaction.followup.send(tr(locale, "case.invalid_rule"), ephemeral=True)
                    return
                rule_ids.append(str(selected_rule.id))
                selected_rule_label = rule_label(selected_rule)

            created_case = await create_case(
                session=session,
                server_id=interaction.guild.id,
                body=ModerationCaseCreateModel(
                    target_user_id=str(user.id),
                    opened_by_user_id=str(interaction.user.id),
                    title=title.strip(),
                    summary=summary_text,
                    rule_ids=rule_ids,
                ),
                opened_by_user_id=interaction.user.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.open_failed", error=error), ephemeral=True)
        return

    rule_suffix = f" {tr(locale, 'modlog.rule_label')}: {selected_rule_label}." if selected_rule_label else ""
    await interaction.followup.send(
        tr(locale, "case.opened", case_id=created_case.id[:8], mention=user.mention, title=created_case.title, rule_suffix=rule_suffix),
        ephemeral=True,
    )


@case_create.autocomplete("rule")
async def case_create_rule_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.cases.manage",
    ):
        return []

    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild_id)
    except Exception:
        return []

    return rule_choices(rules, current)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(
    name="list",
    description="List open moderation cases.",
)
async def cases_list(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
    limit: app_commands.Range[int, 1, 10] = 5,
):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.view", locale=locale):
        return

    try:
        async with get_async_session() as session:
            cases = await fetch_open_case_models(
                session=session,
                server_id=interaction.guild.id,
                user_id=user.id if user else None,
                limit=limit,
            )
            details_by_case_id = {}
            for moderation_case in cases:
                details_by_case_id[moderation_case.id] = await get_case_details(
                    session=session,
                    server_id=interaction.guild.id,
                    case_id=UUID(moderation_case.id),
                )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return

    if not cases:
        suffix = f" for {user.mention}" if user else ""
        await interaction.followup.send(tr(locale, "case.none_open", suffix=suffix), ephemeral=True)
        return

    title = tr(locale, "case.list_title")
    if user is not None:
        title = tr(locale, "case.list_title_for_user", user=user.display_name)
    embed = discord.Embed(title=title, color=discord.Color.blurple())
    embed.set_footer(text=tr(locale, "case.footer", count=len(cases), limit=limit))

    for moderation_case in cases:
        details = details_by_case_id.get(moderation_case.id)
        status = moderation_case.status.value if isinstance(moderation_case.status, CaseStatus) else moderation_case.status
        field_name = _truncate_discord(moderation_case.title, 256)
        value_lines = [
            f"{tr(locale, 'case.dashboard')}: {_case_dashboard_link(interaction.guild.id, moderation_case.id)}",
            f"{tr(locale, 'case.status')}: `{status}`",
            _actor_line(tr(locale, "case.target"), moderation_case.target_user),
            _actor_line(tr(locale, "case.opened_by"), moderation_case.opened_by),
            (
                f"{tr(locale, 'case.stats')}: "
                f"{moderation_case.stats.linked_actions_count} action(s) - "
                f"{moderation_case.stats.rules_count} rule(s) - "
                f"{moderation_case.stats.notes_count} note(s) - "
                f"{moderation_case.stats.evidence_count} evidence"
            ),
        ]

        action_summaries = details.linked_action_summaries if details is not None else []
        if action_summaries:
            action_links = [
                _action_dashboard_link(interaction.guild.id, action.id, action.action_type)
                for action in action_summaries[:5]
            ]
            if len(action_summaries) > 5:
                action_links.append(f"+{len(action_summaries) - 5} more")
            value_lines.append(f"{tr(locale, 'case.actions')}: {', '.join(action_links)}")
        else:
            value_lines.append(f"{tr(locale, 'case.actions')}: {tr(locale, 'case.actions_none')}")

        if moderation_case.summary:
            value_lines.append(f"{tr(locale, 'case.summary')}: {_truncate_discord(moderation_case.summary, 220)}")

        embed.add_field(
            name=field_name,
            value=_truncate_discord("\n".join(value_lines), 1024),
            inline=False,
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


class CaseDashboardView(discord.ui.View):
    def __init__(self, *, server_id: int, case_id: str, locale: str):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label=tr(locale, "case.dashboard"),
                style=discord.ButtonStyle.link,
                url=_dashboard_case_url(server_id, case_id),
            )
        )


async def _case_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    command_name = getattr(getattr(interaction, "command", None), "name", "")
    permission_key = "moderation.cases.view" if command_name == "show" else "moderation.cases.manage"
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key=permission_key,
    ):
        return []
    try:
        async with get_async_session() as session:
            cases = await list_cases(session=session, server_id=interaction.guild_id, limit=25)
    except Exception:
        return []
    return case_choices(cases, current, include_new=False)


async def _open_case_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.cases.manage",
    ):
        return []
    try:
        async with get_async_session() as session:
            cases = await fetch_open_case_models(session=session, server_id=interaction.guild_id, limit=25)
    except Exception:
        return []
    return case_choices(cases, current, include_new=False)


def _parse_case_id(value: str) -> UUID:
    return UUID(str(value).strip())


def _case_detail_embed(details, locale: str, server_id: int) -> discord.Embed:
    case = details.case
    embed = discord.Embed(
        title=f"{tr(locale, 'case.detail_title')} #{case.id[:8]}",
        description=case.title,
        url=_dashboard_case_url(server_id, case.id),
        color=discord.Color.blurple(),
    )
    embed.add_field(name=tr(locale, "case.status"), value=f"`{case.status.value}`", inline=True)
    embed.add_field(name=tr(locale, "case.target"), value=f"<@{case.target_user.user_id}> (`{case.target_user.display_name}`)", inline=True)
    embed.add_field(name=tr(locale, "case.opened_by"), value=f"<@{case.opened_by.user_id}> (`{case.opened_by.display_name}`)", inline=True)
    if case.summary:
        embed.add_field(name=tr(locale, "case.summary"), value=_truncate_discord(case.summary, 1024), inline=False)
    if case.rules:
        embed.add_field(name=tr(locale, "modlog.rules_label"), value="\n".join(f"`{rule.title}`" for rule in case.rules[:10]), inline=False)
    if details.notes:
        embed.add_field(name="Notes", value="\n".join(_truncate_discord(note.note, 160) for note in details.notes[:5]), inline=False)
    if details.evidence:
        embed.add_field(name="Evidence", value="\n".join(item.url or item.text or item.attachment_key or item.evidence_type.value for item in details.evidence[:5]), inline=False)
    if details.linked_action_summaries:
        actions = [
            _action_dashboard_link(
                server_id,
                action.id,
                action.action_number,
                action.action_type,
            )
            for action in details.linked_action_summaries[:5]
        ]
        embed.add_field(name=tr(locale, "case.actions"), value=", ".join(actions), inline=False)
    embed.set_footer(text=f"Case ID: {case.id}")
    return embed


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="show", description="Show moderation case details.")
async def case_show(interaction: discord.Interaction, case: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.view", locale=locale):
        return
    try:
        async with get_async_session() as session:
            details = await get_case_details(session=session, server_id=interaction.guild.id, case_id=_parse_case_id(case))
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(
        embed=_case_detail_embed(details, locale, interaction.guild.id),
        view=CaseDashboardView(server_id=interaction.guild.id, case_id=details.case.id, locale=locale),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="close", description="Close a moderation case.")
async def case_close(interaction: discord.Interaction, case: str):
    await _set_case_status(interaction, case, CaseStatus.CLOSED)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="reopen", description="Reopen a moderation case.")
async def case_reopen(interaction: discord.Interaction, case: str):
    await _set_case_status(interaction, case, CaseStatus.OPEN)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="archive", description="Archive a moderation case.")
async def case_archive(interaction: discord.Interaction, case: str):
    await _set_case_status(interaction, case, CaseStatus.ARCHIVED)


async def _set_case_status(interaction: discord.Interaction, case: str, status: CaseStatus):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            updated = await update_case_status(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                body=ModerationCaseStatusUpdateModel(status=status, closed_by_user_id=str(interaction.user.id)),
                closed_by_user_id=interaction.user.id if status != CaseStatus.OPEN else None,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.status_updated", case_id=updated.id[:8], status=updated.status.value), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="note", description="Add a note to a moderation case.")
async def case_note(interaction: discord.Interaction, case: str, note: str, internal: bool = True):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            created = await add_case_note(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                body=ModerationCaseNoteCreateModel(note=note, is_internal=internal),
                author_user_id=interaction.user.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.note_added", case_id=created.case_id[:8]), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="evidence", description="Add text or URL evidence to a moderation case.")
@app_commands.choices(evidence_type=[app_commands.Choice(name="URL", value="link"), app_commands.Choice(name="Text", value="text")])
async def case_evidence(interaction: discord.Interaction, case: str, evidence_type: app_commands.Choice[str], value: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    parsed_type = EvidenceType.LINK if evidence_type.value == "link" else EvidenceType.NOTE
    try:
        async with get_async_session() as session:
            created = await add_case_evidence(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                body=ModerationCaseEvidenceCreateModel(
                    evidence_type=parsed_type,
                    url=value if parsed_type == EvidenceType.LINK else None,
                    text=value if parsed_type == EvidenceType.NOTE else None,
                ),
                added_by_user_id=interaction.user.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.evidence_added", case_id=created.case_id[:8]), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="add_user", description="Add a related user to a moderation case.")
@app_commands.choices(role=[app_commands.Choice(name="Related", value="related"), app_commands.Choice(name="Target", value="target")])
async def case_add_user(interaction: discord.Interaction, case: str, user: discord.Member, role: app_commands.Choice[str]):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    parsed_role = CaseUserRole.TARGET if role.value == "target" else CaseUserRole.RELATED
    try:
        async with get_async_session() as session:
            updated = await add_user_to_case(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                user_id=user.id,
                role=parsed_role,
                added_by_user_id=interaction.user.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.user_added", mention=user.mention, case_id=updated.id[:8], role=parsed_role.value), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="remove_user", description="Remove a related user from a moderation case.")
async def case_remove_user(interaction: discord.Interaction, case: str, user: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            updated = await remove_user_from_case(session=session, server_id=interaction.guild.id, case_id=_parse_case_id(case), user_id=user.id)
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.user_removed", mention=user.mention, case_id=updated.id[:8]), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="add_rule", description="Add a rule citation to a moderation case.")
async def case_add_rule(interaction: discord.Interaction, case: str, rule: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            rules = await fetch_active_rule_models(session=session, server_id=interaction.guild.id)
            selected_rule = find_rule(rules, rule)
            if selected_rule is None:
                await interaction.followup.send(tr(locale, "case.invalid_rule"), ephemeral=True)
                return
            updated = await upsert_case_rules(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                body=ModerationCaseRulesUpsertModel(rule_ids=[str(selected_rule.id)]),
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.rule_added", rule=rule_label(selected_rule), case_id=updated.id[:8]), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="remove_rule", description="Remove a rule citation from a moderation case.")
async def case_remove_rule(interaction: discord.Interaction, case: str, rule: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            updated = await remove_case_rule(session=session, server_id=interaction.guild.id, case_id=_parse_case_id(case), rule_id=UUID(rule))
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(tr(locale, "case.rule_removed", case_id=updated.id[:8]), ephemeral=True)


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="link_action", description="Link an existing moderation action to a case.")
async def case_link_action(interaction: discord.Interaction, case: str, action_id: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            linked_action = await resolve_moderation_action_reference(
                session,
                server_id=interaction.guild.id,
                reference=action_id,
            )
            if linked_action is None:
                raise ValueError("Moderation action not found")
            updated = await link_action_to_case(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                moderation_action_id=linked_action.id,
                linked_by_user_id=interaction.user.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(
        tr(
            locale,
            "case.action_linked",
            action_number=linked_action.action_number,
            case_id=updated.id[:8],
        ),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.command(name="unlink_action", description="Unlink a moderation action from a case.")
async def case_unlink_action(interaction: discord.Interaction, case: str, action_id: str):
    if interaction.guild is None:
        await interaction.response.send_message(tr(None, "common.server_only"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    locale = await get_server_locale(interaction.guild.id)
    if not await ensure_bot_permission(interaction, "moderation.cases.manage", locale=locale):
        return
    try:
        async with get_async_session() as session:
            linked_action = await resolve_moderation_action_reference(
                session,
                server_id=interaction.guild.id,
                reference=action_id,
            )
            if linked_action is None:
                raise ValueError("Moderation action not found")
            updated = await remove_action_from_case(
                session=session,
                server_id=interaction.guild.id,
                case_id=_parse_case_id(case),
                action_id=linked_action.id,
            )
            await session.commit()
    except Exception as error:
        await interaction.followup.send(tr(locale, "case.details_failed", error=error), ephemeral=True)
        return
    await interaction.followup.send(
        tr(
            locale,
            "case.action_unlinked",
            action_number=linked_action.action_number,
            case_id=updated.id[:8],
        ),
        ephemeral=True,
    )


for _command in (
    case_show,
    case_close,
    case_reopen,
    case_archive,
    case_note,
    case_evidence,
    case_add_user,
    case_remove_user,
    case_add_rule,
    case_remove_rule,
    case_link_action,
    case_unlink_action,
):
    _command.autocomplete("case")(_case_autocomplete)

for _command in (case_add_rule, case_remove_rule):
    _command.autocomplete("rule")(case_create_rule_autocomplete)


async def _case_action_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    if not await has_bot_permission(
        guild_id=interaction.guild_id,
        user_id=interaction.user.id,
        permission_key="moderation.cases.manage",
    ):
        return []
    try:
        async with get_async_session() as session:
            actions = await list_action_summaries(
                session=session,
                server_id=interaction.guild_id,
                limit=100,
            )
    except Exception:
        return []
    return action_choices(actions, current)


for _command in (case_link_action, case_unlink_action):
    _command.autocomplete("action_id")(_case_action_autocomplete)




