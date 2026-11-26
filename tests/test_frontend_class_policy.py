"""Keep the no-utility-class CI guard strict while supporting semantic hooks."""
from scripts.ci.check_frontend_classes import violations


def test_reviewed_static_hooks_can_be_combined():
    assert violations('<section className="crm-surface crm-deal-detail"/>') == []
    assert violations("<p className = 'settings-help'/>") == []


def test_utility_and_unknown_classes_are_rejected():
    assert violations('<div className="crm-surface p-4 md:flex"/>') == [
        (1, "unreviewed CSS classes: md:flex, p-4")]
    assert violations('<div className="unreviewed-component"/>')


def test_dynamic_or_obfuscated_classes_cannot_bypass_review():
    for value in ['{classes}', '{"p-4"}', '{`crm-${kind}`}', '{["p-4"].join(" ")}']:
        assert violations(f'<div className={value}/>') == [
            (1, "className must be a reviewed static string")]


def test_whitespace_and_multiline_class_attributes_are_checked():
    assert violations('<div\n className =\n "p-4"/>') == [(2, "unreviewed CSS classes: p-4")]
