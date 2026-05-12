import textwrap
import pytest
from labs.models import LabResult, Patient


@pytest.mark.django_db
class TestPatientListAPI:
    def test_returns_patients(self, api_client, patients):
        response = api_client.get("/api/teams/lakewood-memorial/patients/")
        assert response.status_code == 200
        assert len(response.data["results"]) > 0

    def test_includes_patient_fields(self, api_client, patients):
        response = api_client.get("/api/teams/lakewood-memorial/patients/")
        patient = response.data["results"][0]
        assert "name" in patient
        assert "mrn" in patient
        assert "date_of_birth" in patient
        assert "team_name" in patient


@pytest.mark.django_db
class TestPatientDetailAPI:
    def test_returns_patient(self, api_client, patients):
        patient = patients["lw1"]
        response = api_client.get(
            f"/api/teams/lakewood-memorial/patients/{patient.id}/"
        )
        assert response.status_code == 200
        assert response.data["name"] == "Chen, David"
        assert response.data["mrn"] == "LM-001"

    def test_includes_allergies(self, api_client, patients, allergies):
        patient = patients["lw1"]
        response = api_client.get(
            f"/api/teams/lakewood-memorial/patients/{patient.id}/"
        )
        assert response.status_code == 200
        assert len(response.data["allergies"]) == 3

    def test_includes_lab_results(self, api_client, patients, lab_results):
        patient = patients["lw1"]
        response = api_client.get(
            f"/api/teams/lakewood-memorial/patients/{patient.id}/"
        )
        assert response.status_code == 200
        assert len(response.data["lab_results"]) == 3


@pytest.mark.django_db
class TestLabResultAPI:
    def test_returns_lab_results(self, api_client, patients, lab_results):
        patient = patients["lw1"]
        response = api_client.get(
            f"/api/teams/lakewood-memorial/patients/{patient.id}/lab-results/"
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 3

    def test_lab_result_fields(self, api_client, patients, lab_results):
        patient = patients["lw1"]
        response = api_client.get(
            f"/api/teams/lakewood-memorial/patients/{patient.id}/lab-results/"
        )
        result = response.data["results"][0]
        assert "test_name" in result
        assert "value" in result
        assert "unit" in result
        assert "effective_date" in result
        assert "observation_data" in result


@pytest.mark.django_db
class TestFHIRIngestion:
    def test_process_fhir_bundle(self, teams):
        from labs.fhir import process_fhir_bundle

        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "test-pt",
                        "identifier": [
                            {"type": {"coding": [{"code": "MR"}]}, "value": "TEST-001"}
                        ],
                        "name": [{"family": "Test", "given": ["Patient"]}],
                        "birthDate": "1990-01-01",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": "test-obs",
                        "status": "final",
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}
                            ]
                        },
                        "subject": {"reference": "Patient/TEST-001"},
                        "effectiveDateTime": "2026-03-10T09:00:00Z",
                        "valueQuantity": {"value": 95, "unit": "mg/dL"},
                        "identifier": [{"value": "ACC-001"}],
                    }
                },
            ],
        }

        result = process_fhir_bundle(bundle, teams["lakewood"])
        assert result["patients"] == 1
        assert result["observations"] == 1
        assert Patient.objects.filter(mrn="TEST-001").exists()
        assert LabResult.objects.filter(accession_number="ACC-001").exists()


@pytest.mark.django_db
class TestRiversideCSVIngestion:
    CSV_HEADER = "patient_name,mrn,date_of_birth,test_name,test_code,value,unit,collection_date,accession_number\n"

    def _run(self, teams, tmp_path, rows):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(self.CSV_HEADER + textwrap.dedent(rows).strip() + "\n")
        from django.core.management import call_command
        call_command("ingest_riverside_csv", str(csv_file))

    def test_creates_patient_and_lab_result(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,03/01/2026,RC-ACC-001
        """)
        assert Patient.objects.filter(team=teams["riverside"], mrn="RC-001").exists()
        assert LabResult.objects.filter(accession_number="RC-ACC-001").exists()

    def test_date_format_us_slash(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,03/01/2026,RC-ACC-001
        """)
        result = LabResult.objects.get(accession_number="RC-ACC-001")
        assert result.effective_date.date().isoformat() == "2026-03-01"

    def test_date_format_iso(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,2026-03-10,RC-ACC-002
        """)
        result = LabResult.objects.get(accession_number="RC-ACC-002")
        assert result.effective_date.date().isoformat() == "2026-03-10"

    def test_date_format_short_year(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Thompson, James",RC-003,11/03/1973,Glucose,2339-0,88,mg/dL,3/9/26,RC-ACC-003
        """)
        result = LabResult.objects.get(accession_number="RC-ACC-003")
        assert result.effective_date.date().isoformat() == "2026-03-09"

    def test_non_numeric_value_stored_as_is(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,>200,mg/dL,03/10/2026,RC-ACC-004
        """)
        assert LabResult.objects.get(accession_number="RC-ACC-004").value == ">200"

    def test_unit_normalized_to_lowercase(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,MG/DL,03/01/2026,RC-ACC-005
        """)
        assert LabResult.objects.get(accession_number="RC-ACC-005").unit == "mg/dl"

    def test_missing_unit_stored_as_empty_string(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Thompson, James",RC-003,11/03/1973,Sodium,2951-2,142,,03/09/2026,RC-ACC-006
        """)
        assert LabResult.objects.get(accession_number="RC-ACC-006").unit == ""

    def test_idempotent(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,03/01/2026,RC-ACC-007
        """)
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,03/01/2026,RC-ACC-007
        """)
        assert LabResult.objects.filter(accession_number="RC-ACC-007").count() == 1

    def test_bad_date_skipped_rest_continues(self, teams, tmp_path):
        self._run(teams, tmp_path, """
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,92,mg/dL,not-a-date,RC-ACC-BAD
            "Garcia, Ana",RC-001,06/15/1988,Glucose,2339-0,95,mg/dL,03/01/2026,RC-ACC-008
        """)
        assert not LabResult.objects.filter(accession_number="RC-ACC-BAD").exists()
        assert LabResult.objects.filter(accession_number="RC-ACC-008").exists()
