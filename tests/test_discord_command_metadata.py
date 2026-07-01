import ast
from pathlib import Path

from fastapi.testclient import TestClient

from api.api_main import app
from api.services.bot_command_catalog import BOT_COMMANDS, get_bot_command, list_bot_commands
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


def test_bot_command_catalog_exposes_moderation_command_details():
    command = get_bot_command("mod.actions.manage")

    assert command is not None
    assert command.invoke == "/mod actions manage"
    assert {component.label for component in command.components} == {
        "Open dashboard",
        "Add info in dashboard",
        "Delete messages",
        "Revert",
    }


def test_bot_command_catalog_endpoint_returns_filterable_contract():
    client = TestClient(app)

    response = client.get("/bot-commands", params={"category": "moderation-cases"})
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2026-06-30"
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

    assert [command.qualified_name for command in context_menu_commands] == ["Import Rules From Message"]


def test_bot_command_catalog_exposes_valid_rbac_permission_keys():
    all_permission_keys = get_all_permission_keys()
    commands_with_rbac = [command for command in BOT_COMMANDS if command.required_rbac_permissions]

    assert commands_with_rbac
    for command in commands_with_rbac:
        assert set(command.required_rbac_permissions).issubset(all_permission_keys)

    assert get_bot_command("mod.warn").required_rbac_permissions == ["moderation.actions.apply.warn"]
    assert get_bot_command("mod.actions.revert").required_rbac_permissions == ["moderation.actions.revert"]
    assert get_bot_command("mod.security.security_lockdown").required_rbac_permissions == ["security.lockdown.manage"]


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


def test_moderation_bot_commands_use_product_rbac_permissions():
    expected = {
        "warn": {"moderation.actions.apply.warn"},
        "mute": {"moderation.actions.apply.mute"},
        "unmute": {"moderation.actions.apply.mute"},
        "kick": {"moderation.actions.apply.kick"},
        "ban": {"moderation.actions.apply.ban"},
        "unban": {"moderation.actions.apply.ban"},
        "actions_list": {"moderation.actions.view"},
        "action_manage": {"moderation.actions.view"},
        "action_revert": {"moderation.actions.revert"},
        "revert_button": {"moderation.actions.revert"},
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
