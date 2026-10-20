"""The words for a feature's matching rule, used by two screens.

Features shows them under the frozen rule read-out; the Mismatches detail row
(`SD70`) shows them beside a wrong answer, because "how was this compared"
is half of "was it really wrong". One function per sentence, so the two
screens cannot word one rule differently. Moved here from `features_view`'s
private `_matching_rule_label` / `_matching_rule_help`, unchanged in wording.
"""

from ra2.domain.feature import Kind, MatchingRule, MatchingRuleKind, ValueType

__all__ = ["rule_help", "rule_label"]


def rule_label(kind: Kind, rule: MatchingRule) -> str:
    if kind is Kind.EXPLORATORY:
        return "n/a — no ground truth"
    if rule.kind is MatchingRuleKind.WITHIN_TOLERANCE:
        return "within tolerance"
    return "exact"


def rule_help(kind: Kind, value_type: ValueType, rule: MatchingRule) -> str:
    if kind is Kind.EXPLORATORY:
        return "no structured counterpart exists to match against."
    if value_type is ValueType.ENUM:
        return "the emitted code must equal the ground-truth code."
    if rule.kind is MatchingRuleKind.WITHIN_TOLERANCE:
        return "matches within the parameter's tolerance, in minutes."
    return "matches after normalisation (mvp-spec.md §8.4)."
