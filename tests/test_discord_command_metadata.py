import ast
from pathlib import Path

import discord
from fastapi.testclient import TestClient

from api.api_main import app
from api.services.bot_command_catalog import (
    BOT_COMMANDS,
    RU_CHOICE_NAMES_BY_VALUE,
    RU_COMMAND_TEXT,
    RU_COMPONENTS_BY_LABEL,
    RU_PARAMETER_DESCRIPTIONS,
    RU_PARAMETER_DESCRIPTIONS_BY_COMMAND,
    get_bot_command,
    list_bot_commands,
)
from api.services.rbac_catalog import get_all_permission_keys


ROOT = Path(__file__).resolve().parents[1]
COMMAND_FILES = [ROOT / "main.py", *sorted((ROOT / "src" / "commands").rglob("*.py"))]
COMMAND_DECORATOR_NAMES = {"command", "Group"}
MAX_COMMAND_DESCRIPTION_LENGTH = 100
MAX_COMMAND_NAME_LENGTH = 32


def _decorator_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _string_keyword(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return None


def test_discord_command_descriptions_fit_sync_limits():
    violations: list[str] = []

    for file_path in COMMAND_FILES:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            calls: list[ast.Call] = []
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                calls.extend(decorator for decorator in node.decorator_list if isinstance(decorator, ast.Call))
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                calls.append(node.value)

            for call in calls:
                if _decorator_name(call) not in COMMAND_DECORATOR_NAMES:
                    continue

                description = _string_keyword(call, "description")
                if description is None:
                    continue

                description_length = len(description)
                if description_length > MAX_COMMAND_DESCRIPTION_LENGTH:
                    relative_path = file_path.relative_to(ROOT)
                    violations.append(
                        f"{relative_path}:{call.lineno} has description length "
                        f"{description_length} > {MAX_COMMAND_DESCRIPTION_LENGTH}"
                    )

    assert violations == []


def test_discord_command_names_fit_sync_limits():
    violations: list[str] = []

    for file_path in COMMAND_FILES:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            calls: list[ast.Call] = []
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                calls.extend(decorator for decorator in node.decorator_list if isinstance(decorator, ast.Call))
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                calls.append(node.value)

            for call in calls:
                if _decorator_name(call) not in COMMAND_DECORATOR_NAMES:
                    continue

                command_name = _string_keyword(call, "name")
                if command_name is None:
                    continue

                command_name_length = len(command_name)
                if command_name_length > MAX_COMMAND_NAME_LENGTH:
                    relative_path = file_path.relative_to(ROOT)
                    violations.append(
                        f"{relative_path}:{call.lineno} has command name length "
                        f"{command_name_length} > {MAX_COMMAND_NAME_LENGTH}"
                    )

    assert violations == []

def _assigned_call(module: ast.Module, variable_name: str) -> ast.Call | None:
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == variable_name:
                return node.value
    return None


def test_top_level_moderation_group_is_short_mod_alias():
    module = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"), filename="main.py")
    moderation_group = _assigned_call(module, "moderation_group")

    assert moderation_group is not None
    assert _decorator_name(moderation_group) == "Group"
    assert _string_keyword(moderation_group, "name") == "mod"


def _function_command_names() -> dict[str, str]:
    command_names: dict[str, str] = {}
    for file_path in COMMAND_FILES:
        module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(module):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or _decorator_name(decorator) != "command":
                    continue
                command_names[node.name] = _string_keyword(decorator, "name") or node.name
    return command_names


def _context_menu_names() -> dict[str, str]:
    context_menu_names: dict[str, str] = {}
    for file_path in COMMAND_FILES:
        module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(module):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if _decorator_name(node.value) != "ContextMenu":
                continue
            name = _string_keyword(node.value, "name")
            if name is None:
                for keyword in node.value.keywords:
                    if keyword.arg != "name" or not isinstance(keyword.value, ast.Call):
                        continue
                    if keyword.value.args and isinstance(keyword.value.args[0], ast.Constant):
                        if isinstance(keyword.value.args[0].value, str):
                            name = keyword.value.args[0].value
            if name is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    context_menu_names[target.id] = name
    return context_menu_names


def _group_paths(module: ast.Module) -> dict[str, list[str]]:
    groups: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _decorator_name(node.value) != "Group":
            continue
        name = _string_keyword(node.value, "name")
        if name is None:
            continue
        parent = None
        for keyword in node.value.keywords:
            if keyword.arg == "parent" and isinstance(keyword.value, ast.Name):
                parent = keyword.value.id
        for target in node.targets:
            if isinstance(target, ast.Name):
                groups[target.id] = (name, parent)

    def build_path(group_variable: str) -> list[str]:
        name, parent = groups[group_variable]
        return [*build_path(parent), name] if parent else [name]

    return {group_variable: build_path(group_variable) for group_variable in groups}


def _registered_slash_qualified_names() -> set[str]:
    module = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"), filename="main.py")
    command_names = _function_command_names()
    command_names.update(_context_menu_names())
    group_paths = _group_paths(module)
    qualified_names: set[str] = set()

    for node in ast.walk(module):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or _decorator_name(decorator) != "command":
                    continue
                if isinstance(decorator.func, ast.Attribute) and isinstance(decorator.func.value, ast.Name):
                    if decorator.func.value.id == "tree":
                        qualified_names.add(_string_keyword(decorator, "name") or node.name)

        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "add_command":
            continue
        if not isinstance(call.func.value, ast.Name) or call.func.value.id not in group_paths:
            continue
        if not call.args or not isinstance(call.args[0], ast.Name):
            continue
        command_name = command_names.get(call.args[0].id)
        if command_name is not None:
            qualified_names.add(" ".join([*group_paths[call.func.value.id], command_name]))

    return qualified_names


def test_bot_command_catalog_covers_registered_discord_commands():
    catalog_qualified_names = {command.qualified_name for command in BOT_COMMANDS}
    registered_qualified_names = _registered_slash_qualified_names()

    assert registered_qualified_names.difference(catalog_qualified_names) == set()
    assert "Import Rules From Message" in catalog_qualified_names
    assert "Link Message to Action" in catalog_qualified_names
    assert "Reply as Modral" in catalog_qualified_names
    assert "Start Moderation Action" in catalog_qualified_names


def test_requested_command_renames_are_registered_and_catalogued():
    registered = _registered_slash_qualified_names()
    catalogued = {command.qualified_name for command in BOT_COMMANDS}
    renamed = {
        "bday add",
        "bday change",
        "bday list",
        "mod bday check",
        "mod cases new",
        "mod actions undo",
        "cat",
    }
    retired_names = {
        "add_my_birthday",
        "change_birthday",
        "birthday_list",
        "check_dr",
        "mod cases create",
        "mod actions revert",
        "cat_text",
    }

    assert renamed.issubset(registered)
    assert renamed.issubset(catalogued)
    assert registered.isdisjoint(retired_names)
    assert catalogued.isdisjoint(retired_names)
    assert {"birthdays_settings", "mod actions list"}.issubset(registered)

    undo = get_bot_command("mod.actions.undo")
    assert undo is not None
    assert undo.parameters[0].name == "action_number"
    assert undo.parameters[0].type == "integer"

    cat = get_bot_command("cat")
    assert cat is not None
    assert cat.parameters[0].name == "text"
    assert cat.parameters[0].required is False


def test_bot_command_catalog_exposes_moderation_command_details():
    assert get_bot_command("mod.actions.manage") is None

    warn_command = get_bot_command("mod.warn")
    assert warn_command is not None
    assert {
        "delete_messages",
        "delete_message_limit",
        "delete_message_channel",
    }.issubset({parameter.name for parameter in warn_command.parameters})

    for command_id in ("mod.mute", "mod.kick", "mod.ban"):
        command = get_bot_command(command_id)
        assert command is not None
        assert {
            "delete_messages",
            "delete_message_limit",
            "delete_message_channel",
        }.issubset({parameter.name for parameter in command.parameters})
        add_warn = next(parameter for parameter in command.parameters if parameter.name == "add_warn")
        assert add_warn.type == "boolean"
        assert add_warn.required is False
        assert add_warn.default == "false"

    reply_command = get_bot_command("context.reply_as_modral")
    assert reply_command is not None
    assert {component.type for component in reply_command.components} == {
        "modal",
        "checkbox",
    }


def test_ban_command_accepts_users_outside_the_guild():
    from src.commands.moderation.actions import ban

    assert ban.callback.__annotations__["user"] is discord.User


def test_bot_command_catalog_endpoint_returns_filterable_contract():
    client = TestClient(app)

    response = client.get("/bot-commands", params={"category": "moderation-cases"})
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2026-08-06"
    assert body["locale"] == "en"
    assert body["available_locales"] == ["en", "ru"]
    assert {command["category"] for command in body["commands"]} == {"moderation-cases"}
    assert "parameters" in body["commands"][0]
    assert "workflow" in body["commands"][0]
    assert "required_rbac_permissions" in body["commands"][0]

    details_response = client.get("/bot-commands/mod.warn")
    assert details_response.status_code == 200
    assert details_response.json()["invoke"] == "/mod warn"
    assert details_response.json()["required_rbac_permissions"] == ["moderation.actions.apply.warn"]


def test_bot_command_catalog_filters_by_discord_type():
    context_menu_commands = list_bot_commands(discord_type="message_context_menu")

    assert [command.qualified_name for command in context_menu_commands] == [
        "Import Rules From Message",
        "Link Message to Action",
        "Reply as Modral",
        "Start Moderation Action",
    ]

    link_command = get_bot_command("context.link_message_to_action")
    assert link_command is not None
    assert link_command.required_rbac_permissions == ["moderation.actions.link_messages"]

    start_command = get_bot_command("context.start_moderation_action")
    assert start_command is not None
    assert {component.label for component in start_command.components}.issuperset(
        {"Action type", "Rule", "Duration", "Moderator commentary"}
    )


def test_bot_command_catalog_exposes_valid_rbac_permission_keys():
    all_permission_keys = get_all_permission_keys()
    commands_with_rbac = [command for command in BOT_COMMANDS if command.required_rbac_permissions]

    assert commands_with_rbac
    for command in commands_with_rbac:
        assert set(command.required_rbac_permissions).issubset(all_permission_keys)

    assert get_bot_command("mod.warn").required_rbac_permissions == ["moderation.actions.apply.warn"]
    assert get_bot_command("mod.actions.undo").required_rbac_permissions == ["moderation.actions.revert"]
    assert get_bot_command("birthdays_settings").required_rbac_permissions == ["birthdays.settings.edit"]
    assert get_bot_command("add_reply").required_rbac_permissions == ["replies.manage"]
    assert get_bot_command("delete_reply").required_rbac_permissions == ["replies.manage"]
    assert get_bot_command("show_replies").required_rbac_permissions == ["replies.view"]
    assert get_bot_command("force_validation").required_rbac_permissions == ["maintenance.memberships.reconcile"]
    lockdown_command = get_bot_command("mod.lockdown")
    assert lockdown_command is not None
    assert lockdown_command.invoke == "/mod lockdown"
    assert lockdown_command.required_rbac_permissions == ["security.lockdown.manage"]
    assert {parameter.name for parameter in lockdown_command.parameters}.issuperset({"enabled", "reason"})


def _function_nodes_by_name() -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    nodes: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}
    for file_path in COMMAND_FILES:
        module = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(module):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                nodes[node.name] = node
    return nodes


def _rbac_permission_calls(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    permission_keys: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Name) or child.func.id != "ensure_bot_permission":
            continue
        for arg in child.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                permission_keys.add(arg.value)
        for keyword in child.keywords:
            if keyword.arg == "permission_key" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    permission_keys.add(keyword.value.value)
    return permission_keys


def test_rule_autocomplete_avoids_network_backed_rbac_resolution():
    nodes = _function_nodes_by_name()
    rule_autocomplete_functions = {
        "warn_rule_autocomplete",
        "mute_rule_autocomplete",
        "action_rule_autocomplete",
        "case_create_rule_autocomplete",
    }

    for function_name in rule_autocomplete_functions:
        node = nodes[function_name]
        called_names = {
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        assert "has_bot_permission" not in called_names


def test_moderation_bot_commands_use_product_rbac_permissions():
    expected = {
        "warn": {"moderation.actions.apply.warn"},
        "mute": {"moderation.actions.apply.mute"},
        "unmute": {"moderation.actions.apply.mute"},
        "kick": {"moderation.actions.apply.kick"},
        "ban": {"moderation.actions.apply.ban"},
        "unban": {"moderation.actions.apply.ban"},
        "actions_list": {"moderation.actions.view"},
        "member_profile": {"moderation.actions.view", "moderation.cases.view"},
        "action_revert": {"moderation.actions.revert"},
        "_open_action_revert_confirmation": {"moderation.actions.revert"},
        "moderation_settings": {"moderation.settings.view"},
        "moderation_set_mute_role": {"moderation.settings.edit"},
        "moderation_set_log_channel": {"moderation.settings.edit"},
        "moderation_clear_log_channel": {"moderation.settings.edit"},
        "moderation_set_language": {"localization.settings.edit"},
        "moderation_create_mute_role": {"moderation.settings.edit"},
        "moderation_set_mute_defaults": {"moderation.settings.edit"},
        "rules_import_message": {"moderation.rules.manage"},
        "rules_import_messages": {"moderation.rules.manage"},
        "rule_add": {"moderation.rules.manage"},
        "rules_list": {"moderation.rules.view"},
        "rules_parse_guide": {"moderation.rules.view"},
        "import_rules_from_message_context": {"moderation.rules.manage"},
        "case_create": {"moderation.cases.manage"},
        "cases_list": {"moderation.cases.view"},
        "case_show": {"moderation.cases.view"},
        "_set_case_status": {"moderation.cases.manage"},
        "case_note": {"moderation.cases.manage"},
        "case_evidence": {"moderation.cases.manage"},
        "case_add_user": {"moderation.cases.manage"},
        "case_remove_user": {"moderation.cases.manage"},
        "case_add_rule": {"moderation.cases.manage"},
        "case_remove_rule": {"moderation.cases.manage"},
        "case_link_action": {"moderation.cases.manage"},
        "case_unlink_action": {"moderation.cases.manage"},
        "security_set_verified_role": {"security.settings.edit"},
        "security_newcomer_role_suggestion": {"security.settings.edit"},
        "security_set_newcomer_role": {"security.settings.edit"},
        "security_create_newcomer_role": {"security.settings.edit"},
        "security_capture_permissions": {"security.settings.edit"},
        "security_lockdown": {"security.lockdown.manage"},
        "verify_member": {"security.settings.edit"},
        "birthdays_settings": {"birthdays.settings.edit"},
        "add_reply": {"replies.manage"},
        "delete_reply": {"replies.manage"},
        "birthday_check": {"birthdays.settings.edit"},
        "show_replies": {"replies.view"},
        "force_validation": {"maintenance.memberships.reconcile"},
    }

    nodes = _function_nodes_by_name()
    missing: list[str] = []
    for function_name, expected_permissions in expected.items():
        node = nodes.get(function_name)
        if node is None:
            missing.append(f"{function_name}: function not found")
            continue
        actual = _rbac_permission_calls(node)
        if not expected_permissions.issubset(actual):
            missing.append(f"{function_name}: expected {sorted(expected_permissions)}, found {sorted(actual)}")

    assert missing == []


def test_only_confirmed_member_commands_are_public():
    public_commands = {command.id for command in BOT_COMMANDS if command.audience == "public_member"}

    assert public_commands == {"bday.add", "bday.change", "bday.list", "cat", "warns"}


def test_public_command_catalog_matches_newcomer_command_allowlist():
    module = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"), filename="main.py")
    allowlist: set[str] | None = None
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "PUBLIC_MEMBER_COMMAND_NAMES" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call) or not node.value.args:
            continue
        values = node.value.args[0]
        if isinstance(values, (ast.Set, ast.Tuple, ast.List)):
            allowlist = {
                item.value
                for item in values.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
        break

    catalog_names = {
        command.qualified_name
        for command in BOT_COMMANDS
        if command.audience == "public_member"
    }
    assert allowlist == catalog_names


def test_bot_command_catalog_endpoint_returns_russian_locale():
    client = TestClient(app)

    response = client.get("/bot-commands/mod.warn", params={"locale": "ru"})
    assert response.status_code == 200
    body = response.json()

    assert body["invoke"] == "/mod warn"
    assert body["summary"] == "Выдать предупреждение участнику, указать правило сервера и записать модераторское действие."
    assert body["parameters"][0]["description"] == "Пользователь Discord."
    assert body["components"][0]["label"] == "Правило"
    assert body["workflow"][0] == "Проверяет, что команда запущена на сервере."


def test_bot_command_catalog_list_returns_russian_locale_metadata():
    client = TestClient(app)

    response = client.get("/bot-commands", params={"locale": "ru", "category": "moderation-actions"})
    assert response.status_code == 200
    body = response.json()

    assert body["locale"] == "ru"
    assert body["available_locales"] == ["en", "ru"]
    assert any(command["summary"].startswith("Выдать предупреждение") for command in body["commands"])


def test_russian_bot_command_catalog_has_no_english_fallbacks():
    assert set(RU_COMMAND_TEXT) == {command.id for command in BOT_COMMANDS}

    missing: list[str] = []
    for command in BOT_COMMANDS:
        translation = RU_COMMAND_TEXT[command.id]
        if not translation.get("summary"):
            missing.append(f"{command.id}: summary")
        if command.workflow and not translation.get("workflow"):
            missing.append(f"{command.id}: workflow")
        if command.notes and not translation.get("notes"):
            missing.append(f"{command.id}: notes")

        command_parameters = RU_PARAMETER_DESCRIPTIONS_BY_COMMAND.get(command.id, {})
        for parameter in command.parameters:
            if parameter.name not in command_parameters and parameter.name not in RU_PARAMETER_DESCRIPTIONS:
                missing.append(f"{command.id}: parameter {parameter.name}")
            for choice in parameter.choices:
                if str(choice.value) not in RU_CHOICE_NAMES_BY_VALUE:
                    missing.append(f"{command.id}: choice {choice.value}")

        for component in command.components:
            if component.label not in RU_COMPONENTS_BY_LABEL:
                missing.append(f"{command.id}: component {component.label}")

    assert missing == []


def test_russian_parameter_help_uses_command_context():
    temp_voice_limit = get_bot_command("tempvoice.limit", locale="ru")
    case_list = get_bot_command("mod.cases.list", locale="ru")
    lockdown = get_bot_command("mod.lockdown", locale="ru")

    assert temp_voice_limit is not None
    assert temp_voice_limit.parameters[0].description == "Лимит участников в канале от 0 до 99; 0 снимает ограничение."
    assert case_list is not None
    assert case_list.parameters[1].description == "Сколько открытых дел показать: от 1 до 10."
    assert lockdown is not None
    assert lockdown.parameters[0].description.startswith("true включает локдаун")
