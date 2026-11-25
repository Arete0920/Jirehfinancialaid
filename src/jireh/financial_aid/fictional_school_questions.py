"""Fixed, versioned question fixtures for the disposable family workspace."""

from dataclasses import dataclass
from datetime import date
from uuid import uuid5

from jireh.schools.demo_seed import DEMO_SCHOOL_A_CODE

from .questionnaire_validation import QuestionnaireValidationError
from .school_question_versions import (
    FictionalSchoolQuestionCatalog, FictionalSchoolQuestionDefinition, ValidatedSchoolQuestionAnswer,
)


_FIXTURES = (
    ("example-checklist", "v1", "boolean", None, "Include the example checklist?"),
    ("example-worksheet", "v1", "enum", ("Worksheet A", "Worksheet B"), "Choose an example worksheet"),
    ("example-worksheet", "v2", "enum", ("Worksheet B", "Worksheet C"), "Choose an example worksheet"),
)


@dataclass(frozen=True, repr=False)
class FictionalSchoolQuestionSet:
    catalog: FictionalSchoolQuestionCatalog
    definitions: tuple[FictionalSchoolQuestionDefinition, ...]
    saved: tuple[ValidatedSchoolQuestionAnswer, ...]

    def validate(self, rows):
        return _validate_rows(self.catalog, self.definitions, rows)


def _validate_rows(catalog, definitions, rows):
    by_version = {(str(item.definition_id), item.version): item for item in definitions}
    if type(rows) is not list or len(rows) > len(by_version):
        raise QuestionnaireValidationError("school_question_rows_invalid")
    seen = set()
    results = []
    for row in rows:
        if (type(row) is not dict or type(row.get("definition_id")) is not str
                or type(row.get("definition_version")) is not str):
            raise QuestionnaireValidationError("school_question_rows_invalid")
        definition_id = row["definition_id"]
        definition = by_version.get((definition_id, row["definition_version"]))
        if definition is None or definition_id in seen:
            raise QuestionnaireValidationError("school_question_binding_invalid")
        results.append(catalog.validate_answer(
            school_id=definition.school_id, academic_year_id=definition.academic_year_id,
            definition_id=definition.definition_id, definition_version=definition.version, record=row,
        ))
        seen.add(definition_id)
    return tuple(results)


def school_questions_for_draft(draft, saved_rows):
    """Pin existing answers to their historical definitions and use current versions for new answers."""
    definitions = ()
    if (draft.school.code == DEMO_SCHOOL_A_CODE
            and draft.academic_year.name == "2026-27"
            and draft.academic_year.start_date == date(2026, 8, 1)
            and draft.academic_year.end_date == date(2027, 6, 30)):
        definitions = tuple(FictionalSchoolQuestionDefinition(
            school_id=draft.school_id, academic_year_id=draft.academic_year_id,
            definition_id=uuid5(draft.academic_year_id, f"jireh-fixture:{key}"),
            question_key=key, version=version, answer_type=answer_type, enum_options=options,
        ) for key, version, answer_type, options, _ in _FIXTURES)
    catalog = FictionalSchoolQuestionCatalog(definitions)
    saved = _validate_rows(catalog, definitions, saved_rows)
    # The fixture lists versions in publication order. An existing answer keeps its version.
    selected = {definition.definition_id: definition for definition in definitions}
    selected.update({answer.definition.definition_id: answer.definition for answer in saved})
    return FictionalSchoolQuestionSet(catalog, tuple(selected.values()), saved)


def fictional_question_label(definition):
    return next(label for key, version, _, _, label in _FIXTURES
                if key == definition.question_key and version == definition.version)
