from __future__ import annotations

import importlib

import pytest


def test_pipeline_failure_alert_script_sends_alert_with_output_tail(monkeypatch, tmp_path):
    alert_script = importlib.import_module("scripts.send_pipeline_failure_alert")

    output_file = tmp_path / "pipeline.log"
    output_file.write_text(
        "\n".join(
            [
                "debug before json",
                "{",
                '  "status": "failed",',
                '  "stages": {',
                '    "deliver_digest": {',
                '      "status": "failed",',
                '      "error": "\'digest_html\'",',
                '      "error_type": "KeyError"',
                "    }",
                "  },",
                '  "failed_stages": ["deliver_digest"]',
                "}",
            ]
        ),
        encoding="utf-8",
    )

    fake_config = {
        "paths": {},
        "email": {
            "alert_recipient": "zeizyy@gmail.com",
            "alert_subject_prefix": "[ALERT] Newsletter Curator Failure",
        },
    }
    fake_service = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(alert_script.delivery_main, "load_config", lambda: fake_config)
    monkeypatch.setattr(alert_script.delivery_main, "get_gmail_service", lambda paths: fake_service)

    def fake_send_delivery_failure_alert_if_needed(
        config,
        service,
        *,
        source: str,
        result=None,
        exception=None,
        traceback_text: str = "",
    ):
        captured["config"] = config
        captured["service"] = service
        captured["source"] = source
        captured["result"] = result
        captured["exception"] = exception
        captured["traceback_text"] = traceback_text
        return True

    monkeypatch.setattr(
        alert_script.delivery_main,
        "send_delivery_failure_alert_if_needed",
        fake_send_delivery_failure_alert_if_needed,
    )

    alert_script.main(
        [
            "--source",
            "run_daily_pipeline.sh",
            "--exit-status",
            "137",
            "--output-file",
            str(output_file),
        ]
    )

    assert captured["config"] == fake_config
    assert captured["service"] is fake_service
    assert captured["source"] == "run_daily_pipeline.sh"
    assert captured["result"]["stages"]["deliver_digest"]["error_type"] == "KeyError"
    assert isinstance(captured["exception"], RuntimeError)
    assert str(captured["exception"]) == "daily pipeline exited with status 137"
    assert "Pipeline output:" in captured["traceback_text"]
    assert '"error_type": "KeyError"' in captured["traceback_text"]


def test_pipeline_failure_alert_script_exits_when_alert_is_skipped(monkeypatch, tmp_path):
    alert_script = importlib.import_module("scripts.send_pipeline_failure_alert")

    output_file = tmp_path / "pipeline.log"
    output_file.write_text("Killed\n", encoding="utf-8")

    monkeypatch.setattr(alert_script.delivery_main, "load_config", lambda: {"paths": {}, "email": {}})
    monkeypatch.setattr(alert_script.delivery_main, "get_gmail_service", lambda paths: object())
    monkeypatch.setattr(
        alert_script.delivery_main,
        "send_delivery_failure_alert_if_needed",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(SystemExit, match="failure alert was skipped"):
        alert_script.main(
            [
                "--exit-status",
                "137",
                "--output-file",
                str(output_file),
            ]
        )


def test_pipeline_failure_alert_script_skips_upstream_failure_when_delivery_completed(
    monkeypatch,
    tmp_path,
):
    alert_script = importlib.import_module("scripts.send_pipeline_failure_alert")

    output_file = tmp_path / "pipeline.log"
    output_file.write_text(
        "\n".join(
            [
                "{",
                '  "status": "partial_failure",',
                '  "stages": {',
                '    "fetch_gmail": {"status": "failed"},',
                '    "deliver_digest": {"status": "completed"}',
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(alert_script.delivery_main, "load_config", lambda: {"paths": {}, "email": {}})
    monkeypatch.setattr(alert_script.delivery_main, "get_gmail_service", lambda paths: object())

    def fail_send_alert(*args, **kwargs):
        raise AssertionError("delivery-successful upstream failures should not email")

    monkeypatch.setattr(
        alert_script.delivery_main,
        "send_delivery_failure_alert_if_needed",
        fail_send_alert,
    )

    alert_script.main(
        [
            "--exit-status",
            "1",
            "--output-file",
            str(output_file),
        ]
    )
