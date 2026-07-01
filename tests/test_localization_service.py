from src.modules.localization.catalog import TRANSLATIONS
from src.modules.localization.service import tr


def test_ru_catalog_source_values_are_not_mojibake():
    mojibake_markers = ("Ã", "Â", "\ufffd")
    broken = [
        key
        for key, value in TRANSLATIONS["ru"].items()
        if any(marker in value for marker in mojibake_markers)
    ]
    assert broken == []


def test_ru_settings_labels_are_not_mojibake():
    assert tr("ru", "settings.show_title") == "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438:"
    assert tr("ru", "settings.mute_role", value="Muted") == "- \u0420\u043e\u043b\u044c \u043c\u0443\u0442\u0430: `Muted`"
    assert tr("ru", "settings.mod_log_channel", value="#logs") == "- \u041a\u0430\u043d\u0430\u043b \u043c\u043e\u0434-\u043b\u043e\u0433\u043e\u0432: #logs"


def test_ru_rules_guide_example_label_is_not_mojibake():
    assert tr("ru", "rules.guide_example") == "\u041f\u0440\u0438\u043c\u0435\u0440:"


def test_ru_new_moderation_labels_are_not_mojibake():
    assert tr(
        "ru",
        "case.opened",
        case_id="abc12345",
        mention="@user",
        title="Case title",
        rule_suffix="",
    ) == "\u041e\u0442\u043a\u0440\u044b\u0442 \u043a\u0435\u0439\u0441 #abc12345 \u0434\u043b\u044f @user: Case title."
    assert tr("ru", "action.revert_button") == "\u041e\u0442\u043a\u0430\u0442\u0438\u0442\u044c"
