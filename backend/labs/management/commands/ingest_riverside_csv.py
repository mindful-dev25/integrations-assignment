import csv
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from labs.models import LabResult, Patient, Team

DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"]


def _parse_date(value):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value!r}")


class Command(BaseCommand):
    help = "Ingest Riverside Community lab data from CSV"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to riverside_community_labs.csv")

    def handle(self, *args, **options):
        try:
            team = Team.objects.get(slug="riverside-community")
        except Team.DoesNotExist:
            raise CommandError("Team 'riverside-community' not found. Run seed_data first.")

        stats = {
            "rows": 0,
            "patients_created": 0,
            "patients_updated": 0,
            "results_created": 0,
            "results_updated": 0,
            "errors": [],
        }
        seen_mrns = set()

        try:
            f = open(options["csv_path"], newline="")
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['csv_path']}")

        with f:
            for row in csv.DictReader(f):
                stats["rows"] += 1
                try:
                    self._process_row(row, team, stats, seen_mrns)
                except Exception as e:
                    stats["errors"].append(
                        f"Row {stats['rows']} ({row.get('accession_number', '?')}): {e}"
                    )

        self.stdout.write(f"Processed {stats['rows']} rows")
        self.stdout.write(
            f"Patients: {stats['patients_created']} created, {stats['patients_updated']} updated"
        )
        self.stdout.write(
            f"Lab results: {stats['results_created']} created, {stats['results_updated']} updated"
        )
        if stats["errors"]:
            self.stdout.write(self.style.WARNING(f"{len(stats['errors'])} rows skipped:"))
            for err in stats["errors"]:
                self.stdout.write(f"  {err}")
        else:
            self.stdout.write(self.style.SUCCESS("No errors"))

    def _process_row(self, row, team, stats, seen_mrns):
        effective_date = _parse_date(row["collection_date"])

        patient, created = Patient.objects.update_or_create(
            team=team,
            mrn=row["mrn"],
            defaults={
                "name": row["patient_name"],
                "date_of_birth": _parse_date(row["date_of_birth"]).date(),
                "patient_data": {
                    "source": "riverside-csv",
                    "mrn": row["mrn"],
                    "patient_name": row["patient_name"],
                    "date_of_birth": row["date_of_birth"],
                },
            },
        )
        if row["mrn"] not in seen_mrns:
            if created:
                stats["patients_created"] += 1
            else:
                stats["patients_updated"] += 1
            seen_mrns.add(row["mrn"])

        _, created = LabResult.objects.update_or_create(
            accession_number=row["accession_number"],
            defaults={
                "patient": patient,
                "test_name": row["test_name"],
                "test_code": row["test_code"],
                "value": row["value"],
                "unit": row["unit"].lower(),
                "effective_date": effective_date,
                "observation_data": dict(row),
            },
        )
        if created:
            stats["results_created"] += 1
        else:
            stats["results_updated"] += 1
