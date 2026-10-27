"""Bounded imported-output comparison; never executes or promotes a candidate."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.files import LocalInput


def utf8_text(value):
    if isinstance(value, str):
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Use valid Unicode text without unpaired surrogates.') from None
    return value


class Prediction(BaseModel):
    # Exact output bytes after JSON decoding matter, including surrounding whitespace.
    model_config = ConfigDict(extra='forbid', strict=True)
    example_id: str = Field(min_length=1, max_length=100)
    output: str | None = Field(max_length=1000)

    _utf8 = field_validator('*')(utf8_text)


class ExperimentInput(LocalInput):
    dataset_id: str = Field(min_length=1, max_length=100)
    dataset_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate_name: str = Field(min_length=3, max_length=120)
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    predictions: list[Prediction] = Field(min_length=1, max_length=100)

    _utf8 = field_validator('*')(utf8_text)

    @model_validator(mode='after')
    def unique_predictions(self):
        if len({p.example_id for p in self.predictions}) != len(self.predictions):
            raise ValueError('Supply each frozen example exactly once.')
        return self


class BuiltinRunInput(LocalInput):
    """Run a bundled deterministic candidate; no model, download or training."""
    dataset_id: str = Field(min_length=1, max_length=100)
    dataset_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate: Literal['contact_ranker_v1']
    # Reviewer convention for abstentions; null counts abstentions as incorrect.
    abstention_output: str | None = Field(default=None, min_length=1, max_length=1000)

    _utf8 = field_validator('*')(utf8_text)
