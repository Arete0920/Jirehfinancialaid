"""Grant-scoped, read-only synthetic director workload HTTP tests."""
from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from jireh.financial_aid.models import AidApplication, AidApplicationStudent, AidAuditEvent
from jireh.financial_aid.services import get_or_create_annual_draft, select_student_for_draft
from jireh.schools.models import AcademicYear, Household, HouseholdAccess, School, SchoolStaffAccess, Student
from jireh.schools.services import link_student_to_household


class DirectorWorkloadHTTPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User=get_user_model()
        cls.parent=User.objects.create_user(username="workload-parent")
        cls.other_parent=User.objects.create_user(username="workload-other-parent")
        cls.parent_b=User.objects.create_user(username="workload-parent-b")
        cls.director_a=User.objects.create_user(username="workload-director-a")
        cls.director_b=User.objects.create_user(username="workload-director-b")
        cls.admin=User.objects.create_superuser(username="workload-admin",email="admin@example.invalid",password="synthetic-only")
        cls.school_a=School.objects.create(code="workload-school-a",name="Synthetic A")
        cls.school_b=School.objects.create(code="workload-school-b",name="Synthetic B")
        cls.year_a=AcademicYear.objects.create(school=cls.school_a,name="2026-27",start_date=date(2026,8,1),end_date=date(2027,6,30))
        cls.year_future=AcademicYear.objects.create(school=cls.school_a,name="2027-28",start_date=date(2027,8,1),end_date=date(2028,6,30))
        cls.year_b=AcademicYear.objects.create(school=cls.school_b,name="2026-27",start_date=date(2026,8,1),end_date=date(2027,6,30))
        cls.house_a=Household.objects.create(school=cls.school_a,name="Private A")
        cls.house_separate=Household.objects.create(school=cls.school_a,name="Private Separate")
        cls.house_b=Household.objects.create(school=cls.school_b,name="Private B")
        for house,parent in ((cls.house_a,cls.parent),(cls.house_separate,cls.other_parent),(cls.house_b,cls.parent_b)):
            HouseholdAccess.objects.create(household=house,user=parent)
        for school,director in ((cls.school_a,cls.director_a),(cls.school_b,cls.director_b)):
            SchoolStaffAccess.objects.create(school=school,user=director,role=SchoolStaffAccess.ROLE_AID_DIRECTOR)
        cls.shared=Student.objects.create(school=cls.school_a,first_name="Shared",last_name="Fictional")
        cls.sibling=Student.objects.create(school=cls.school_a,first_name="Sibling",last_name="Fictional")
        cls.child_b=Student.objects.create(school=cls.school_b,first_name="Other",last_name="Fictional")
        for house,child in ((cls.house_a,cls.shared),(cls.house_a,cls.sibling),
                            (cls.house_separate,cls.shared),(cls.house_b,cls.child_b)):
            link_student_to_household(school_id=house.school_id,household_id=house.pk,student_id=child.pk)
        for parent,school,house,year,children in (
            (cls.parent,cls.school_a,cls.house_a,cls.year_a,(cls.shared,cls.sibling)),
            (cls.other_parent,cls.school_a,cls.house_separate,cls.year_a,(cls.shared,)),
            (cls.parent_b,cls.school_b,cls.house_b,cls.year_b,(cls.child_b,))):
            get_or_create_annual_draft(user=parent,school_id=school.pk,household_id=house.pk,academic_year_id=year.pk)
            for child in children:
                select_student_for_draft(user=parent,school_id=school.pk,household_id=house.pk,academic_year_id=year.pk,student_id=child.pk)

    def url(self,school=None,year=None):
        return reverse("jireh_staff_application_summary",kwargs={
            "school_id":school or self.school_a.pk,"academic_year_id":year or self.year_a.pk,
        })

    def test_same_school_two_households_three_links_not_awards(self):
        self.client.force_login(self.director_a)
        response=self.client.get(self.url())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{
            "school_id":str(self.school_a.pk),
            "academic_year_id":str(self.year_a.pk),
            "draft_application_records":2,
            "distinct_draft_households":2,
            "selected_household_student_links":3,
            "application_unit":"household_application_not_student",
            "selection_unit":"household_student_link_not_distinct_student",
            "financial_submissions_or_awards_included":False,
        })
        self.assertIn("no-store",response["Cache-Control"].lower())
        self.assertNotIn("Private",response.content.decode())

    def test_school_b_and_future_year_independent(self):
        self.client.force_login(self.director_b)
        result=self.client.get(self.url(self.school_b,self.year_b))
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["draft_application_records"],1)
        self.client.force_login(self.director_a)
        result=self.client.get(self.url(year=self.year_future))
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["draft_application_records"],0)

    def test_wrong_director_parent_superuser_and_anonymous_denied(self):
        self.assertEqual(self.client.get(self.url()).status_code,403)
        for user in (self.parent,self.director_b,self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response=self.client.get(self.url())
                self.assertEqual(response.status_code,404)
                self.assertEqual(response.json(),{"detail":"Not found."})

    def test_cross_school_year_and_revocation_denied(self):
        self.client.force_login(self.director_a)
        for url in (self.url(self.school_b,self.year_b),self.url(self.school_a,self.year_b),self.url(year=uuid4())):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url,HTTP_X_SCHOOL_ID=str(self.school_a.pk)).status_code,404)
        SchoolStaffAccess.objects.filter(school=self.school_a,user=self.director_a).update(is_active=False)
        self.assertEqual(self.client.get(self.url()).status_code,404)

    def test_safe_methods_do_not_mutate_application_or_audit(self):
        self.client.force_login(self.director_a)
        before=(AidApplication.objects.count(),AidApplicationStudent.objects.count(),AidAuditEvent.objects.count())
        self.assertEqual(self.client.head(self.url()).status_code,200)
        for method in (self.client.post,self.client.put,self.client.delete):
            self.assertEqual(method(self.url()).status_code,405)
        self.assertEqual((AidApplication.objects.count(),AidApplicationStudent.objects.count(),AidAuditEvent.objects.count()),before)
