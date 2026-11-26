"""Unit tests for the deterministic verticals/registry helpers.

Pure-function coverage of the goal→department mapping (including the
out-of-set fallback chain: in-set keyword match → alias → template default
department → round-robin) and the goal-title truncation rule. No client,
no DB, no LLM (Codex review P2-1, 2026-08-29).
"""

from backend.templates import TEMPLATES, truncate_goal_title
from backend.verticals import (
    DEFAULT_DEPARTMENTS,
    DEPARTMENTS,
    VERTICAL_DEPARTMENTS,
    canonical_vertical,
    map_goal_to_department,
    resolve_departments,
)


class TestCanonicalVertical:
    def test_case_insensitive_and_whitespace(self):
        assert canonical_vertical("retail & e-commerce") == "Retail & E-Commerce"
        assert canonical_vertical("  OTHER  ") == "Other"

    def test_blank_or_unknown_returns_none(self):
        assert canonical_vertical(None) is None
        assert canonical_vertical("") is None
        assert canonical_vertical("   ") is None
        assert canonical_vertical("Plumbing & Ducts") is None


class TestResolveDepartments:
    def test_known_vertical_returns_its_four(self):
        expected = list(VERTICAL_DEPARTMENTS["Retail & E-Commerce"])
        assert resolve_departments("Retail & E-Commerce") == expected

    def test_other_unset_unknown_all_default(self):
        assert resolve_departments("Other") == list(DEFAULT_DEPARTMENTS)
        assert resolve_departments(None) == list(DEFAULT_DEPARTMENTS)
        assert resolve_departments("some unknown value") == list(DEFAULT_DEPARTMENTS)

    def test_every_vertical_maps_to_four_closed_set_departments(self):
        for vertical, depts in VERTICAL_DEPARTMENTS.items():
            assert len(depts) == 4, vertical
            assert set(depts) <= set(DEPARTMENTS), vertical


class TestMapGoalToDepartment:
    RETAIL = ["Customer Success", "Operations", "Marketing", "Sales"]

    def test_keyword_match_in_set_wins(self):
        assert (
            map_goal_to_department("Reduce ticket resolution time", self.RETAIL, None, 0)
            == "Customer Success"
        )

    def test_keyword_out_of_set_falls_back_to_alias(self):
        # "forecast" -> Supply Chain (not in RETAIL) -> alias Operations.
        assert (
            map_goal_to_department("Improve demand forecasting accuracy", self.RETAIL, None, 0)
            == "Operations"
        )

    def test_keyword_out_of_set_falls_back_to_template_department(self):
        # "fraud" -> Risk & Compliance (not in RETAIL, no alias); the
        # template's own department (Sales) IS in the set -> Sales.
        assert (
            map_goal_to_department("Detect fraudulent transactions", self.RETAIL, "Sales", 0)
            == "Sales"
        )

    def test_no_keyword_round_robin_by_goal_index(self):
        assert map_goal_to_department("An entirely unrelated goal", self.RETAIL, "Finance", 0) == "Customer Success"
        assert map_goal_to_department("An entirely unrelated goal", self.RETAIL, "Finance", 3) == "Sales"

    def test_empty_set_falls_back_to_template_department_or_operations(self):
        assert map_goal_to_department("whatever", [], "Finance", 0) == "Finance"
        assert map_goal_to_department("whatever", [], None, 0) == "Operations"

    def test_every_template_goal_maps_into_every_vertical_set(self):
        # Deterministic end-to-end property: for every template and every
        # vertical, each goal maps to a department inside that vertical's
        # 4-set (never outside it, never None).
        for template_id, template in TEMPLATES.items():
            for vertical, depts in VERTICAL_DEPARTMENTS.items():
                dept_set = list(depts)
                for i, goal in enumerate(template["default_goals"]):
                    mapped = map_goal_to_department(goal, dept_set, template["default_department"], i)
                    assert mapped in dept_set, f"{template_id}/{vertical}/{goal!r} -> {mapped!r}"


class TestTruncateGoalTitle:
    def test_short_goal_unchanged(self):
        assert truncate_goal_title("Short goal") == "Short goal"
        assert truncate_goal_title("") == ""
        assert truncate_goal_title(None) == ""

    def test_truncates_at_word_boundary_with_ellipsis(self):
        goal = "Reduce average ticket resolution time from hours to minutes for tier-1 issues across all customer channels and regions"
        assert len(goal) > 100  # the test requires an over-limit goal
        out = truncate_goal_title(goal)
        assert out.endswith("…")
        cut = out[:-1]
        assert len(cut) <= 100
        assert cut in goal, "result (sans ellipsis) must be a prefix of the goal"
        # Cut at a word boundary: the next goal char after the cut is a space.
        assert goal[len(cut)] == " "

    def test_exactly_at_limit_unchanged(self):
        goal = "x" * 50 + " " + "y" * 50  # exactly 101 chars -> truncate
        assert truncate_goal_title("z" * 100) == "z" * 100

    def test_single_long_token_hard_cut(self):
        out = truncate_goal_title("x" * 150)
        assert out == "x" * 100 + "…"
