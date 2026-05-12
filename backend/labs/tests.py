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
