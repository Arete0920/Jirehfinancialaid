"""Fail-closed synthetic tests for pure CROWN-derived school draft reporting."""
import unittest
from uuid import UUID

from jireh.financial_aid.workload import WorkloadIntegrityError, summarize_draft_workload

SCHOOL=UUID("11111111-1111-4111-8111-111111111111")
SCHOOL_B=UUID("99999999-9999-4999-8999-999999999999")
YEAR=UUID("22222222-2222-4222-8222-222222222222")
YEAR_B=UUID("88888888-8888-4888-8888-888888888888")
H1=UUID("33333333-3333-4333-8333-333333333333")
H2=UUID("44444444-4444-4444-8444-444444444444")
APP1=UUID("55555555-5555-4555-8555-555555555555")
APP2=UUID("66666666-6666-4666-8666-666666666666")
CHILD=UUID("77777777-7777-4777-8777-777777777777")
CHILD2=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

def app(application=APP1,house=H1,school=SCHOOL,year=YEAR,status="DRAFT"):
    return {"id":application,"school_id":school,"academic_year_id":year,"household_id":house,"status":status}

def selected(application=APP1,house=H1,student=CHILD,school=SCHOOL,year=YEAR):
    return {"application_id":application,"application__school_id":school,
            "application__academic_year_id":year,"application__household_id":house,
            "household_student__household_id":house,"household_student__student_id":student}

def summarize(apps=(),selections=()):
    return summarize_draft_workload(school_id=SCHOOL,academic_year_id=YEAR,
                                    applications=apps,selections=selections)

class DraftWorkloadTests(unittest.TestCase):
    def test_empty_school_has_explicit_zero_counts_and_truthful_units(self):
        self.assertEqual(summarize(),{
            "draft_application_records":0,"distinct_draft_households":0,
            "selected_household_student_links":0,
            "application_unit":"household_application_not_student",
            "selection_unit":"household_student_link_not_distinct_student",
            "financial_submissions_or_awards_included":False})

    def test_two_siblings_are_one_household_application(self):
        result=summarize([app()],[selected(),selected(student=CHILD2)])
        self.assertEqual(result["draft_application_records"],1)
        self.assertEqual(result["selected_household_student_links"],2)

    def test_shared_child_does_not_merge_separate_households(self):
        result=summarize([app(),app(APP2,H2)],[selected(),selected(APP2,H2,CHILD)])
        self.assertEqual(result["draft_application_records"],2)
        self.assertEqual(result["distinct_draft_households"],2)
        self.assertEqual(result["selected_household_student_links"],2)

    def test_cross_school_year_or_non_draft_rejected(self):
        for bad in (app(school=SCHOOL_B),app(year=YEAR_B),
                    app(status="SUBMITTED"),app(status="APPROVED"),app(house=None)):
            with self.subTest(bad=bad),self.assertRaises(WorkloadIntegrityError):
                summarize([bad])

    def test_invalid_student_scope_cannot_inflate_count(self):
        for bad in (selected(school=SCHOOL_B),selected(year=YEAR_B),
                    selected(house=H2),selected(application=APP2),selected(student=None),
                    dict(selected(),**{"household_student__household_id":H2})):
            with self.subTest(bad=bad),self.assertRaises(WorkloadIntegrityError):
                summarize([app()],[bad])

    def test_duplicate_application_household_or_selection_rejected(self):
        for apps,links in (([app(),app()],[]),([app(),app(APP2,H1)],[]),
                           ([app()],[selected(),selected()])):
            with self.assertRaises(WorkloadIntegrityError):
                summarize(apps,links)

    def test_invalid_identifier_and_scope_rejected(self):
        for apps,links in ((["invalid"],[]),([dict(app(),id=True)],[]),
                           ([dict(app(),id="bad")],[]),
                           ([app()],[dict(selected(),application_id=True)])):
            with self.assertRaises(WorkloadIntegrityError):
                summarize(apps,links)
        for school,year in (("bad",YEAR),(SCHOOL,None),(SCHOOL,True)):
            with self.assertRaises(WorkloadIntegrityError):
                summarize_draft_workload(school_id=school,academic_year_id=year,applications=[],selections=[])

    def test_no_financial_information_returned(self):
        result=summarize([app()|{"family_name":"Private","income_cents":1000000}])
        self.assertEqual(result["draft_application_records"],1)
        self.assertNotIn("Private",str(result))
        self.assertNotIn("income",str(result))

if __name__=="__main__":unittest.main()
