from __future__ import annotations

import importlib

import pytest

from tests.helpers import write_temp_config


def test_main_skips_alert_email_when_alert_recipient_blank(monkeypatch, tmp_path):
    main = importlib.import_module("main")

    config_path = write_temp_config(
        tmp_path,
        overrides={
            "email": {
                "digest_recipients": [],
                "alert_recipient": "",
                "alert_subject_prefix": "[ALERT] Newsletter Curator Failure",
            }
        },
    )
    monkeypatch.setattr(main, "CONFIG_PATH", str(config_path))

    fake_service = object()
    monkeypatch.setattr(main, "get_gmail_service", lambda paths: fake_service)

    def fail_run_job(config, service):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "run_job", fail_run_job)

    def fail_send_email(*args, **kwargs):
        raise AssertionError("alert email should be skipped when alert_recipient is blank")

    monkeypatch.setattr(main, "send_email", fail_send_email)

    with pytest.raises(RuntimeError, match="boom"):
        main.main()
