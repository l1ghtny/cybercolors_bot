import ast
from pathlib import Path


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
