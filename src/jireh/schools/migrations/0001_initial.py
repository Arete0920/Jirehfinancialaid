# Initial standalone Jireh school and household schema.
import uuid

from django.db import migrations, models
from django.db.models import F, Q
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="School",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("is_active", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="AcademicYear",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=32)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("school", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="academic_years", to="schools.school")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("school", "name"), name="jireh_school_year_unique"),
                    models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="jireh_year_end_after_start"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Household",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=160)),
                ("is_active", models.BooleanField(default=True)),
                ("school", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="households", to="schools.school")),
            ],
        ),
        migrations.CreateModel(
            name="Student",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("school", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="students", to="schools.school")),
            ],
        ),
        migrations.CreateModel(
            name="HouseholdStudent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("household", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="student_links", to="schools.household")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="household_links", to="schools.student")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("household", "student"), name="jireh_household_student_unique"),
                ],
            },
        ),
    ]
