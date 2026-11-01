from netcoop.collectors import temperature as t
from netcoop.messages import MessageType, NCPMessage
from uuid import uuid4

LHM_SAMPLE = {
    "Text": "Sensor", "Children": [{
        "Text": "MY-LAPTOP", "Children": [
            {"Text": "Intel Core i5-1135G7", "Children": [
                {"Text": "Temperatures", "Children": [
                    {"Text": "Core #1", "Value": "58.0 \u00b0C", "Children": []},
                    {"Text": "CPU Package", "Value": "63.0 \u00b0C", "Children": []},
                ]}]},
            {"Text": "NVIDIA GeForce MX450", "Children": [
                {"Text": "Temperatures", "Children": [
                    {"Text": "GPU Core", "Value": "90.0 \u00b0C", "Children": []}]}]},
        ]}]}


def test_lhm_prefers_cpu_package_and_ignores_gpu():
    val, name = t.parse_lhm_json(LHM_SAMPLE)
    assert val == 63.0 and name == "CPU Package"


def test_lhm_handles_mangled_degree_sign():
    tree = {"Text": "Sensor", "Children": [{"Text": "PC", "Children": [
        {"Text": "AMD Ryzen 5", "Children": [
            {"Text": "Core (Tctl/Tdie)", "Value": "71.5 \u00c2\u00b0C", "Children": []}]}]}]}
    val, _ = t.parse_lhm_json(tree)
    assert val == 71.5


def test_lhm_no_sensor():
    val, reason = t.parse_lhm_json({"Text": "Sensor", "Children": []})
    assert val is None and "no CPU" in reason


def test_fallback_to_estimate_when_everything_fails(monkeypatch):
    c = t.TemperatureCollector()
    c.providers = [("a", lambda: (None, "nope")), ("b", lambda: (None, "nope"))]
    r = c.read()
    assert r.kind == "estimated" and r.value_c is None
    assert len(r.tried) == 2


def test_first_success_wins():
    c = t.TemperatureCollector()
    good = t.TemperatureReading(60.0, "x", "real")
    c.providers = [("a", lambda: (None, "no")), ("b", lambda: (good, ""))]
    assert c.read().value_c == 60.0


def test_demo_mode_is_labelled_simulated():
    c = t.TemperatureCollector(demo_mode=True)
    c.providers = []
    r = c.read()
    assert r.kind == "simulated"


def test_temperature_to_message_all_kinds_validate():
    readings = [
        t.TemperatureReading(61.5, "sensor", "real", "CPU package"),
        t.TemperatureReading(None, "estimate", "estimated", "not degrees C", 72.0),
        t.TemperatureReading(55.0, "demo", "simulated", "demo only"),
        t.TemperatureReading(None, "none", "unavailable", "no sensor"),
    ]
    for reading in readings:
        message = t.temperature_to_message(reading, uuid4())
        validated = NCPMessage.model_validate(message.model_dump())
        assert validated.message_type == MessageType.TELEMETRY_SNAPSHOT
        assert validated.payload["kind"] == reading.kind
        assert set(("temp_c", "source", "kind", "thermal_stress_index", "detail")) <= set(validated.payload)
        if reading.kind == "real":
            assert validated.payload["data_quality"]["source"] == "real"
            assert validated.payload["temp_c"] == 61.5
        elif reading.kind == "estimated":
            assert validated.payload["data_quality"]["source"] == "estimated"
            assert validated.payload["temp_c"] is None
        elif reading.kind == "simulated":
            assert validated.payload["data_quality"]["source"] == "simulated"
        else:
            assert validated.payload["temp_c"] is None
            assert validated.payload["data_quality"]["completeness"] == 0.0
            assert validated.payload["data_quality"]["missing_fields"] == ["temp_c"]
