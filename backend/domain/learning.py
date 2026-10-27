"""Explicit human review and local dataset preparation. No training executor."""
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from backend.domain.files import LocalInput


class LearningSource(LocalInput):
    kind: Literal['feedback', 'quality_audit']
    id: str = Field(min_length=1, max_length=100)
    research_id: str | None = Field(default=None, min_length=1, max_length=100)
    unit_type: Literal['contacts', 'claims'] | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def source_fields(self):
        if self.kind == 'feedback' and any(value is not None for value in (self.research_id, self.unit_type, self.target_id)):
            raise ValueError('Contact feedback takes only its feedback ID.')
        if self.kind == 'quality_audit' and not all((self.research_id, self.unit_type, self.target_id)):
            raise ValueError('A quality source needs a baseline, case, unit type and target.')
        return self


class ExampleReview(LocalInput):
    source: LearningSource
    expected_source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_revision: int = Field(ge=0, strict=True)
    decision: Literal['include', 'exclude']
    reviewer: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=3, max_length=500)
    input_text: str = Field(default='', max_length=2000)
    observed_output: str = Field(default='', max_length=500)
    expected_output: str = Field(default='', max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    redaction_confirmed: bool = Field(default=False, strict=True)
    permission_basis: str = Field(default='', max_length=300)
    business_group: str = Field(default='', max_length=120)
    use_scope: Literal['local_evaluation', 'local_training'] = 'local_evaluation'

    @model_validator(mode='after')
    def inclusion_review(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(not value or len(value) > 100 for value in self.evidence_ids):
            raise ValueError('Choose distinct, nonempty evidence IDs of at most 100 characters.')
        if self.decision == 'include' and not all((self.input_text, self.observed_output, self.expected_output,
                                                  self.evidence_ids, self.redaction_confirmed, self.permission_basis)):
            raise ValueError('Inclusion requires reviewed input/output, evidence, redaction confirmation and source permission basis.')
        text = '\n'.join((self.input_text, self.observed_output, self.expected_output, self.reason, self.permission_basis, self.business_group, self.reviewer))
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:api[_ -]?key|password|authorization)\s*[:=]\s*\S+', text, re.I):
            raise ValueError('Remove credential values before saving learning material.')
        return self


class ExampleSelection(LocalInput):
    id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, strict=True)


class DatasetInput(LocalInput):
    name: str = Field(min_length=3, max_length=120)
    purpose: Literal['evaluation', 'training'] = 'evaluation'
    split: Literal['development', 'holdout'] = 'development'
    mode: Literal['live', 'synthetic']
    examples: list[ExampleSelection] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_examples(self):
        if len({example.id for example in self.examples}) != len(self.examples):
            raise ValueError('Select each example once.')
        if self.purpose == 'training' and self.split == 'holdout':
            raise ValueError('Holdout datasets cannot be used for training.')
        return self


def domain_group(url):
    """Conservative grouping without a PSL dependency; may over-group co.uk, etc."""
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    return '.'.join(host.split('.')[-2:])
