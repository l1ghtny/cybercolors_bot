from dataclasses import dataclass

from fastapi import HTTPException, status

from api.models.rbac import RbacCatalogModel, RbacPermissionModel, RbacPresetModel


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    group: str
    label: str
    description: str


@dataclass(frozen=True)
class PresetDefinition:
    key: str
    label: str
    description: str
    permission_keys: tuple[str, ...]


PERMISSIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition("overview.view", "read", "View overview", "View server overview and setup status."),
    PermissionDefinition("activity.view", "read", "View activity", "View activity and message analytics."),
    PermissionDefinition("audit.timeline.view", "read", "View audit timeline", "View server timeline and audit events."),
    PermissionDefinition("moderation.actions.view", "read", "View actions", "View moderation action history."),
    PermissionDefinition("moderation.cases.view", "read", "View cases", "View moderation cases."),
    PermissionDefinition("moderation.rules.view", "read", "View rules", "View moderation rules."),
    PermissionDefinition("moderation.monitoring.view", "read", "View monitoring", "View monitored users and monitoring queues."),
    PermissionDefinition("moderation.settings.view", "read", "View moderation settings", "View moderation settings."),
    PermissionDefinition("security.settings.view", "read", "View security settings", "View security and newcomer settings."),
    PermissionDefinition("temp_voice.settings.view", "read", "View temp voice settings", "View temporary voice channel settings and archive status."),
    PermissionDefinition("birthdays.settings.view", "read", "View birthday settings", "View birthday settings."),
    PermissionDefinition("replies.view", "read", "View replies", "View bot replies."),
    PermissionDefinition("ai.settings.view", "read", "View AI settings", "View AI settings and moderation suggestions."),
    PermissionDefinition("ai.suggestions.view", "read", "View AI suggestions", "View AI moderation suggestions."),
    PermissionDefinition("ai.decisions.view", "read", "View AI decisions", "View AI moderation decision logs."),
    PermissionDefinition("ai.knowledge.view", "read", "View AI knowledge", "View AI knowledge sources, indexing status, and retrieval previews."),
    PermissionDefinition("moderation.actions.apply.warn", "moderation", "Apply warns", "Warn members from the dashboard or bot."),
    PermissionDefinition("moderation.actions.apply.mute", "moderation", "Apply mutes", "Mute and unmute members."),
    PermissionDefinition("moderation.actions.apply.kick", "moderation", "Apply kicks", "Kick members."),
    PermissionDefinition("moderation.actions.apply.ban", "moderation", "Apply bans", "Ban and unban members."),
    PermissionDefinition("moderation.actions.revert", "moderation", "Revert actions", "Revert moderation actions."),
    PermissionDefinition("moderation.cases.manage", "moderation", "Manage cases", "Create, update, close, and annotate moderation cases."),
    PermissionDefinition("moderation.rules.manage", "moderation", "Manage rules", "Create and update moderation rules."),
    PermissionDefinition("moderation.rules.edit", "moderation", "Edit rules manually", "Manually edit, restore, and permanently delete moderation rules."),
    PermissionDefinition("moderation.monitoring.manage", "moderation", "Manage monitoring", "Manage monitored users and queue decisions."),
    PermissionDefinition("moderation.monitoring.rules.manage", "moderation", "Manage monitoring rules", "Manage monitoring rule configuration."),
    PermissionDefinition("birthdays.records.manage", "birthdays", "Manage birthday records", "Add and update member birthdays."),
    PermissionDefinition("moderation.settings.edit", "settings", "Edit moderation settings", "Edit moderation settings."),
    PermissionDefinition("security.settings.edit", "settings", "Edit security settings", "Edit security and newcomer settings."),
    PermissionDefinition("temp_voice.settings.edit", "settings", "Edit temp voice settings", "Configure temporary voice trigger channels and owner controls."),
    PermissionDefinition("security.lockdown.manage", "settings", "Manage lockdown", "Enable or disable server lockdown."),
    PermissionDefinition("localization.settings.edit", "settings", "Edit localization", "Edit server localization settings."),
    PermissionDefinition("overview.settings.edit", "settings", "Edit overview settings", "Choose roles shown in the server overview."),
    PermissionDefinition("dashboard.access.manage", "admin", "Manage dashboard access", "Manage coarse dashboard access users and roles."),
    PermissionDefinition("rbac.manage", "admin", "Manage RBAC", "Manage feature permissions and presets."),
    PermissionDefinition(
        "commands.visibility.manage",
        "admin",
        "Manage Discord command visibility",
        "Manage which Discord roles, members, and channels can see and use bot commands.",
    ),
    PermissionDefinition("birthdays.settings.edit", "settings", "Edit birthday settings", "Edit birthday settings and messages."),
    PermissionDefinition("replies.manage", "settings", "Manage replies", "Create, update, delete, and duplicate bot replies."),
    PermissionDefinition("ai.settings.edit", "settings", "Edit AI settings", "Edit AI settings."),
    PermissionDefinition("ai.knowledge.manage", "settings", "Manage AI knowledge", "Create, update, delete, and reindex AI knowledge sources."),
    PermissionDefinition("ai.suggestions.review", "moderation", "Review AI suggestions", "Approve, tweak, or dismiss AI moderation suggestions."),
)

PERMISSION_KEYS: frozenset[str] = frozenset(permission.key for permission in PERMISSIONS)
VIEWER_PERMISSION_KEYS: tuple[str, ...] = tuple(
    permission.key for permission in PERMISSIONS if permission.group == "read"
)


PRESETS: tuple[PresetDefinition, ...] = (
    PresetDefinition(
        "viewer",
        "Viewer",
        "Can view dashboard surfaces without mutating moderation state.",
        VIEWER_PERMISSION_KEYS,
    ),
    PresetDefinition(
        "junior_moderator",
        "Junior moderator",
        "Can warn users and help with case notes and evidence.",
        VIEWER_PERMISSION_KEYS
        + (
            "moderation.actions.apply.warn",
            "moderation.cases.manage",
            "birthdays.records.manage",
        ),
    ),
    PresetDefinition(
        "moderator",
        "Moderator",
        "Can mute users and manage cases and monitoring decisions.",
        VIEWER_PERMISSION_KEYS
        + (
            "moderation.actions.apply.warn",
            "moderation.actions.apply.mute",
            "moderation.cases.manage",
            "moderation.monitoring.manage",
            "birthdays.records.manage",
        ),
    ),
    PresetDefinition(
        "senior_moderator",
        "Senior moderator",
        "Can manage stronger moderation actions and moderation rules.",
        VIEWER_PERMISSION_KEYS
        + (
            "moderation.actions.apply.warn",
            "moderation.actions.apply.mute",
            "moderation.actions.apply.kick",
            "moderation.actions.apply.ban",
            "moderation.actions.revert",
            "moderation.cases.manage",
            "moderation.rules.manage",
            "moderation.monitoring.manage",
            "moderation.monitoring.rules.manage",
            "birthdays.records.manage",
            "ai.suggestions.review",
        ),
    ),
    PresetDefinition(
        "admin",
        "Admin",
        "Can administer dashboard, moderation, security, localization, AI, and RBAC settings.",
        tuple(permission.key for permission in PERMISSIONS),
    ),
)

PRESET_KEYS: frozenset[str] = frozenset(preset.key for preset in PRESETS)
PRESETS_BY_KEY: dict[str, PresetDefinition] = {preset.key: preset for preset in PRESETS}


def get_all_permission_keys() -> set[str]:
    return set(PERMISSION_KEYS)


def expand_preset(preset: str | None) -> set[str]:
    if preset is None:
        return set()
    preset_definition = PRESETS_BY_KEY.get(preset)
    if not preset_definition:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown RBAC preset: {preset}",
        )
    return set(preset_definition.permission_keys)


def validate_permission_keys(permission_keys: list[str] | set[str]) -> list[str]:
    unknown = sorted(set(permission_keys).difference(PERMISSION_KEYS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown RBAC permission keys: {', '.join(unknown)}",
        )
    return sorted(set(permission_keys))


def validate_preset(preset: str | None) -> str | None:
    if preset is None:
        return None
    if preset not in PRESET_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown RBAC preset: {preset}",
        )
    return preset


def expand_assignment_permissions(preset: str | None, permission_keys: list[str]) -> list[str]:
    validate_preset(preset)
    explicit_keys = validate_permission_keys(permission_keys)
    return sorted(expand_preset(preset).union(explicit_keys))


def get_rbac_catalog() -> RbacCatalogModel:
    return RbacCatalogModel(
        permissions=[
            RbacPermissionModel(
                key=permission.key,
                group=permission.group,
                label=permission.label,
                description=permission.description,
            )
            for permission in PERMISSIONS
        ],
        presets=[
            RbacPresetModel(
                key=preset.key,
                label=preset.label,
                description=preset.description,
                permission_keys=list(preset.permission_keys),
            )
            for preset in PRESETS
        ],
    )
