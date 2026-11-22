"""Deterministic checks shared by the local and LangSmith benchmarks."""
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolResultCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    equals: dict[str, Any] = Field(default_factory=dict)
    reply_fields: list[str] = Field(default_factory=list)
    includes: dict[str, str] = Field(default_factory=dict)
    contains: dict[str, str] = Field(default_factory=dict)


class ScenarioChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_tools: bool = False
    forbidden_tools: list[str] = Field(default_factory=list)
    classification: dict[str, Any] = Field(default_factory=dict)
    specialist_escalation: bool | None = None
    qa_min: dict[str, int] = Field(default_factory=dict)
    qa_max: dict[str, int] = Field(default_factory=dict)
    qa_verdicts: list[str] = Field(default_factory=list)
    reply_requires: list[str] = Field(default_factory=list)
    reply_forbids: list[str] = Field(default_factory=list)
    tool_results: list[ToolResultCheck] = Field(default_factory=list)
    manual_criteria: list[int] = Field(default_factory=list)


def check_tools(expected, actual, *, ordered=False) -> tuple[bool, float]:
    remaining = list(actual)
    if expected == "none":
        return not remaining, float(not remaining)

    required = list(expected)
    matched = 0
    for requirement in required:
        for index, call in enumerate(remaining):
            if call.agent != requirement["agent"] or call.tool != requirement["tool"]:
                continue
            if not all(
                key in call.args and str(call.args[key]).strip().casefold() == str(value).strip().casefold()
                for key, value in requirement.get("args", {}).items()
            ):
                continue
            matched += 1
            if ordered:
                remaining = remaining[index + 1:]
            else:
                remaining.pop(index)
            break
    return matched == len(required), round(matched / len(required), 4) if required else 1.0


def check_scenario(spec, *, classification=None, draft=None, qa=None, reply="", calls=()) -> dict[str, bool]:
    rules = ScenarioChecks.model_validate(spec)
    classification = classification or {}
    draft = draft or {}
    qa = qa or {}
    checks = {}

    for key, value in rules.classification.items():
        checks[f"classification.{key}"] = key in classification and classification[key] == value
    if rules.specialist_escalation is not None:
        checks["specialist_escalation"] = draft.get("requiere_escalado") is rules.specialist_escalation
    if rules.forbidden_tools:
        checks["forbidden_tools"] = all(call.tool not in rules.forbidden_tools for call in calls)
    if rules.qa_verdicts:
        checks["qa_verdict"] = qa.get("veredicto") in rules.qa_verdicts
    for key, threshold in rules.qa_min.items():
        checks[f"qa_min.{key}"] = key in qa and qa[key] >= threshold
    for key, threshold in rules.qa_max.items():
        checks[f"qa_max.{key}"] = key in qa and qa[key] <= threshold
    for index, pattern in enumerate(rules.reply_requires, 1):
        checks[f"reply_requires.{index}"] = bool(re.search(pattern, reply, re.IGNORECASE))
    for index, pattern in enumerate(rules.reply_forbids, 1):
        checks[f"reply_forbids.{index}"] = not re.search(pattern, reply, re.IGNORECASE)
    for index, rule in enumerate(rules.tool_results, 1):
        checks[f"tool_result.{rule.tool}.{index}"] = any(
            call.tool == rule.tool and call.result is not None and _result_matches(rule, call.result, reply)
            for call in calls
        )
    return checks


def _result_matches(rule: ToolResultCheck, result: dict, reply: str) -> bool:
    return (
        all(key in result and result[key] == value for key, value in rule.equals.items())
        and all(isinstance(result.get(key), list) and value in result[key] for key, value in rule.includes.items())
        and all(
            isinstance(result.get(key), str) and re.search(pattern, result[key], re.IGNORECASE)
            for key, pattern in rule.contains.items()
        )
        and all(
            isinstance(result.get(key), str) and result[key] and re.search(rf"(?<![\w-]){re.escape(result[key])}(?![\w/?#%=&-])", reply)
            for key in rule.reply_fields
        )
    )
