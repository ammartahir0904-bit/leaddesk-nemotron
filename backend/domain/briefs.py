"""Offer planning is user input and hypotheses, never facts about a prospect."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ShortText = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[^\r\n]+$")]
HypothesisText = Annotated[str, Field(min_length=1, max_length=1600)]
CheckText = Annotated[str, Field(min_length=1, max_length=250, pattern=r"^[^\r\n]+$")]


class OfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    offer: str = Field(min_length=3, max_length=1000)
    target_geography: str = Field(min_length=2, max_length=200)
    problem: str | None = Field(default=None, max_length=600)
    capabilities: list[ShortText] = Field(default_factory=list, max_length=6)
    service_geography: str | None = Field(default=None, max_length=200)
    exclusions: list[ShortText] = Field(default_factory=list, max_length=6)
    price: str | None = Field(default=None, max_length=120)

    @field_validator("problem", "service_geography", "price", mode="before")
    @classmethod
    def empty_is_unknown(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("capabilities", "exclusions")
    @classmethod
    def unique_entries(cls, values):
        return list(dict.fromkeys(values))


class HypothesisEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: HypothesisText
    review: Literal["unreviewed", "kept", "rejected"] = "unreviewed"


class BriefEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1, strict=True)
    input: OfferInput
    hypotheses: list[HypothesisEdit] = Field(min_length=1, max_length=4)
    verification_checks: list[CheckText] = Field(min_length=1, max_length=10)


class GeneratedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    hypotheses: list[HypothesisText] = Field(min_length=1, max_length=4)
    verification_checks: list[CheckText] = Field(min_length=1, max_length=10)


def unknowns(inputs: OfferInput) -> dict[str, str]:
    missing = {name: "Not supplied by you." for name in ("problem", "service_geography", "price")
               if getattr(inputs, name) is None}
    if not inputs.capabilities:
        missing["capabilities"] = "No specific capabilities were supplied."
    return missing | {
        "business_location": "Target geography is a preference, not evidence of a business address or service area.",
        "buyer_need": "Hypotheses require source evidence and review of existing alternatives.",
        "buying_intent": "No prospect has confirmed interest.",
        "buyer_budget": "Your offer price is not evidence of a prospect's budget.",
    }


def document(inputs: OfferInput, hypotheses: list[dict], checks: list[str], *, method: str,
             model_hash: str | None = None) -> dict:
    return {"schema_version": 1, "input": inputs.model_dump(), "hypotheses": hypotheses,
            "verification_checks": checks, "unknowns": unknowns(inputs),
            "generation": {"method": method, "model_hash": model_hash},
            "scope": "Planning only. Kept hypotheses are not confirmed business facts or approval for outreach."}


def rules_draft(inputs: OfferInput) -> dict:
    hypotheses = [{"text": f"Investigate whether businesses serving {inputs.target_geography} have a need addressed by this offer: {inputs.offer}",
                   "review": "unreviewed", "origin": "rules"}]
    if inputs.problem:
        hypotheses.append({"text": f"Investigate whether the stated problem occurs for a prospect: {inputs.problem}",
                           "review": "unreviewed", "origin": "rules"})
    checks = ["Establish the official business and branch before attributing contacts.",
              "Check the business address and service area against the target geography.",
              "Find source evidence of the stated need; record absent or contradictory evidence.",
              "Check existing solutions and alternative explanations before suggesting the offer.",
              "Apply exclusions and contact suppressions before considering outreach.",
              "Keep interest and budget unknown unless supported by a documented interaction."]
    return document(inputs, hypotheses, checks, method="rules")


def edited_document(edit: BriefEdit) -> dict:
    return document(edit.input, [h.model_dump() | {"origin": "user"} for h in edit.hypotheses],
                    edit.verification_checks, method="user_edit")


def invalidate_reviews_after_input_change(current: dict, previous: dict) -> dict:
    if current["input"] == previous["input"]:
        return current
    return current | {"hypotheses": [h | {"review": "unreviewed"} if h["review"] == "kept" else h
                                    for h in current["hypotheses"]]}
