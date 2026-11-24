"""Pure school-question version contracts for disposable fictional fixtures."""

from dataclasses import dataclass
import re
from uuid import UUID

from .questionnaire_validation import (
    QuestionnaireValidationError,
    validate_typed_question_answer,
    validate_typed_question_definition,
)


_QUESTION_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")


@dataclass(frozen=True, slots=True, repr=False)
class FictionalSchoolQuestionDefinition:
    """One version of a fictional question. The definition ID spans its versions."""

    school_id: UUID
    academic_year_id: UUID
    definition_id: UUID
    question_key: str
    version: str
    answer_type: str
    enum_options: tuple[str, ...] | None = None

    def __post_init__(self):
        if any(type(value) is not UUID or value.int == 0
               for value in (self.school_id, self.academic_year_id, self.definition_id)):
            raise QuestionnaireValidationError("question_definition_scope_invalid")
        if (type(self.question_key) is not str or _QUESTION_KEY.fullmatch(self.question_key) is None
                or type(self.version) is not str or _VERSION.fullmatch(self.version) is None):
            raise QuestionnaireValidationError("question_definition_identity_invalid")
        validate_typed_question_definition(answer_type=self.answer_type, enum_options=self.enum_options)


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedSchoolQuestionAnswer:
    definition: FictionalSchoolQuestionDefinition
    value: bool | str


@dataclass(frozen=True, slots=True, repr=False)
class FictionalSchoolQuestionCatalog:
    """Immutable caller-supplied versions, with no implicit current version."""

    definitions: tuple[FictionalSchoolQuestionDefinition, ...]

    def __post_init__(self):
        if type(self.definitions) is not tuple:
            raise QuestionnaireValidationError("question_catalog_invalid")
        bindings_by_id = {}
        ids_by_binding = {}
        versions = set()
        for definition in self.definitions:
            if type(definition) is not FictionalSchoolQuestionDefinition:
                raise QuestionnaireValidationError("question_catalog_invalid")
            definition_id = definition.definition_id
            binding = (definition.school_id, definition.academic_year_id, definition.question_key)
            version = (definition_id, definition.version)
            if (bindings_by_id.setdefault(definition_id, binding) != binding
                    or ids_by_binding.setdefault(binding, definition_id) != definition_id
                    or version in versions):
                raise QuestionnaireValidationError("question_catalog_conflict")
            versions.add(version)

    def validate_answer(
        self, *, school_id: UUID, academic_year_id: UUID, definition_id: UUID,
        definition_version: str, record: object,
    ) -> ValidatedSchoolQuestionAnswer:
        """Validate against a version selected by an independently authorized caller."""
        if (any(type(value) is not UUID for value in (school_id, academic_year_id, definition_id))
                or type(definition_version) is not str):
            raise QuestionnaireValidationError("question_version_unavailable")
        definition = next((item for item in self.definitions if (
            item.school_id == school_id and item.academic_year_id == academic_year_id
            and item.definition_id == definition_id and item.version == definition_version
        )), None)
        if definition is None:
            raise QuestionnaireValidationError("question_version_unavailable")
        if type(record) is not dict or set(record) != {"definition_id", "definition_version", "answer"}:
            raise QuestionnaireValidationError("question_answer_record_invalid")
        if (type(record["definition_id"]) is not str or record["definition_id"] != str(definition_id)
                or type(record["definition_version"]) is not str
                or record["definition_version"] != definition_version):
            raise QuestionnaireValidationError("question_answer_binding_invalid")
        value = validate_typed_question_answer(
            value=record["answer"], answer_type=definition.answer_type,
            enum_options=definition.enum_options,
        )
        return ValidatedSchoolQuestionAnswer(definition=definition, value=value)
