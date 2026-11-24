"""Fictional question versions and answer scope contracts."""

from dataclasses import FrozenInstanceError, replace
import unittest
from uuid import UUID, uuid4

from jireh.financial_aid.questionnaire_validation import QuestionnaireValidationError

from jireh.financial_aid.school_question_versions import (
    FictionalSchoolQuestionCatalog, FictionalSchoolQuestionDefinition,
)


class SchoolQuestionVersionTests(unittest.TestCase):
    def setUp(self):
        self.school_id = uuid4()
        self.year_id = uuid4()
        self.question_id = uuid4()
        self.first = FictionalSchoolQuestionDefinition(
            school_id=self.school_id, academic_year_id=self.year_id,
            definition_id=self.question_id, question_key="fictional-choice", version="v1",
            answer_type="enum", enum_options=("FIXTURE_A", "FIXTURE_B"),
        )
        self.second = replace(self.first, version="v2", enum_options=("FIXTURE_B", "FIXTURE_C"))
        self.catalog = FictionalSchoolQuestionCatalog((self.first, self.second))

    def _record(self, version="v2", answer="FIXTURE_C", **extra):
        return {"definition_id": str(self.question_id), "definition_version": version,
                "answer": answer, **extra}

    def _validate(self, record, **overrides):
        target = {
            "school_id": self.school_id, "academic_year_id": self.year_id,
            "definition_id": self.question_id, "definition_version": "v2",
        }
        return self.catalog.validate_answer(record=record, **(target | overrides))

    def test_current_answer_cannot_select_an_older_version(self):
        result = self._validate(self._record())
        self.assertEqual((result.definition, result.value), (self.second, "FIXTURE_C"))
        self.assertNotIn("FIXTURE_C", repr(result))
        with self.assertRaisesRegex(QuestionnaireValidationError, "^question_answer_binding_invalid$"):
            self._validate(self._record("v1", "FIXTURE_A"))
        with self.assertRaisesRegex(QuestionnaireValidationError, "^question_answer_not_allowed$"):
            self._validate(self._record(answer="FIXTURE_A"))

    def test_known_historical_answer_uses_its_pinned_options(self):
        result = self._validate(self._record("v1", "FIXTURE_A"), definition_version="v1")
        self.assertEqual((result.definition, result.value), (self.first, "FIXTURE_A"))
        with self.assertRaises(FrozenInstanceError):
            self.first.enum_options = ("FIXTURE_C",)
        with self.assertRaises(FrozenInstanceError):
            self.catalog.definitions = (self.second,)

    def test_trusted_scope_must_match_school_year_id_and_version(self):
        for scope in ({"school_id": uuid4()}, {"academic_year_id": uuid4()},
                      {"definition_id": uuid4()}, {"definition_version": "v9"},
                      {"school_id": str(self.school_id)}, {"academic_year_id": UUID(int=0)}):
            with self.subTest(scope=scope):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^question_version_unavailable$"):
                    self._validate(self._record(), **scope)
        candidate = self._record()
        candidate["definition_id"] = str(uuid4())
        with self.assertRaisesRegex(QuestionnaireValidationError, "^question_answer_binding_invalid$"):
            self._validate(candidate)

    def test_exact_typed_records_preserve_explicit_false_and_reject_overposting(self):
        boolean = replace(self.first, answer_type="boolean", enum_options=None)
        self.catalog = FictionalSchoolQuestionCatalog((boolean,))
        self.assertIs(self._validate(self._record("v1", False), definition_version="v1").value, False)
        for value in (None, 0, "false", {"value": False}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^question_answer_type_invalid$"):
                    self._validate(self._record("v1", value), definition_version="v1")
        for record in (self._record("v1", True, school_id=str(self.school_id)),
                       {"definition_id": str(self.question_id), "definition_version": "v1"}):
            with self.assertRaisesRegex(QuestionnaireValidationError, "^question_answer_record_invalid$"):
                self._validate(record, definition_version="v1")

    def test_catalog_rejects_duplicate_versions_and_ambiguous_identities(self):
        for conflicting in (
            replace(self.first, enum_options=("FIXTURE_C",)), self.first,
            replace(self.first, definition_id=uuid4(), version="v3"),
            replace(self.first, school_id=uuid4(), version="v3"),
            replace(self.first, academic_year_id=uuid4(), version="v3"),
            replace(self.first, question_key="other-key", version="v3"),
        ):
            with self.subTest(conflicting=conflicting):
                with self.assertRaisesRegex(QuestionnaireValidationError, "^question_catalog_conflict$"):
                    FictionalSchoolQuestionCatalog((self.first, conflicting))
        unrelated = replace(self.first, school_id=uuid4(), definition_id=uuid4())
        separate = FictionalSchoolQuestionCatalog((self.first, unrelated))
        self.assertEqual(len(separate.definitions), 2)

    def test_invalid_definitions_use_stable_errors(self):
        for fields in ({"school_id": UUID(int=0)}, {"academic_year_id": "invalid"},
                       {"question_key": ""}, {"version": "v1\n"}, {"definition_id": UUID(int=0)},
                       {"answer_type": "text"}, {"enum_options": ["FIXTURE_A"]},
                       {"enum_options": ("FIXTURE_A", "FIXTURE_A")}):
            with self.subTest(fields=fields):
                with self.assertRaises(QuestionnaireValidationError):
                    replace(self.first, **fields)
        with self.assertRaisesRegex(QuestionnaireValidationError, "^question_catalog_invalid$"):
            FictionalSchoolQuestionCatalog([self.first])
