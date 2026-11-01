import server


def test_interoperability_catalog_has_all_presentation_message_types():
    catalog = server.interoperability_catalog()
    assert [item["type"] for item in catalog["message_types"]] == [
        "task_request", "finding", "probe_request", "probe_response",
        "conflict_notice", "error", "report",
    ]
    assert "E_UNIT_MISMATCH" in catalog["named_validation_outcomes"]


def test_result_parameter_criteria_preserves_actual_report_values():
    report = {"incident_id": "INC-1", "confidence": 0.8, "confidence_breakdown": {"belief_top": 0.9}}
    criteria = server.result_parameter_criteria(report)
    parameters = {item["name"]: item for item in criteria["parameters"]}
    assert parameters["incident_id"]["value"] == "INC-1"
    assert parameters["confidence"]["value"] == 0.8
    assert parameters["alternative_causes"]["present"] is False
