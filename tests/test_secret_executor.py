from __future__ import annotations

from porcaria.config.schema import SecretCfg
from porcaria.shellout import Completed
from porcaria.sinks.secret import executor


def test_parse_pass_ls_returns_leaf_entries():
    output = """porcaria-accessible
├── emory.edu
│   └── tnesbi2
└── example.com
    ├── personal
    └── work
"""
    assert executor.parse_pass_ls(output, "porcaria-accessible") == [
        "porcaria-accessible/emory.edu/tnesbi2",
        "porcaria-accessible/example.com/personal",
        "porcaria-accessible/example.com/work",
    ]


def test_run_selection_skip_signal():
    report = executor.run_selection(SecretCfg(), "PASS_SKIP")
    assert report.skipped
    assert report.outcome is None


def test_run_selection_not_found_signal():
    report = executor.run_selection(SecretCfg(), "PASS_NOT_FOUND")
    assert not report.ok
    assert report.outcome is not None
    assert report.outcome.kind == "not_found"
    assert "no matching" in report.outcome.error


def test_run_selection_rejects_outside_prefix():
    report = executor.run_selection(SecretCfg(), "PASS_COPY other-store/example")
    assert not report.ok
    assert report.outcome is not None
    assert report.outcome.kind == "invalid_format"
    assert "outside allowed prefix" in report.outcome.error


def test_run_selection_rejects_entry_not_in_pass_list(monkeypatch):
    monkeypatch.setattr(
        executor,
        "list_entries",
        lambda cfg: ["porcaria-accessible/emory.edu/tnesbi2"],
    )
    report = executor.run_selection(SecretCfg(), "PASS_COPY porcaria-accessible/missing")
    assert not report.ok
    assert report.outcome is not None
    assert report.outcome.kind == "not_found"
    assert "not found" in report.outcome.error


def test_run_selection_asks_pass_to_copy_to_clipboard(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(
        executor,
        "list_entries",
        lambda cfg: ["porcaria-accessible/emory.edu/tnesbi2"],
    )

    def fake_run(argv, *, timeout=60.0, cwd=None, env=None, stdin=None, check=False):
        calls.append(argv)
        return Completed(0, "Copied entry to clipboard. Will clear in 45 seconds.\n", "")

    monkeypatch.setattr(executor, "run", fake_run)

    report = executor.run_selection(
        SecretCfg(),
        "PASS_COPY porcaria-accessible/emory.edu/tnesbi2",
    )

    assert report.ok
    assert calls == [
        ["pass", "show", "-c", "porcaria-accessible/emory.edu/tnesbi2"],
    ]


def test_run_selection_reports_immediate_pass_failure(monkeypatch):
    monkeypatch.setattr(
        executor,
        "list_entries",
        lambda cfg: ["porcaria-accessible/emory.edu/tnesbi2"],
    )

    monkeypatch.setattr(
        executor,
        "run",
        lambda argv, **kwargs: Completed(1, "", "pinentry canceled"),
    )
    report = executor.run_selection(
        SecretCfg(),
        "PASS_COPY porcaria-accessible/emory.edu/tnesbi2",
    )

    assert not report.ok
    assert report.outcome is not None
    assert "exited 1" in report.outcome.error


def test_run_selection_reports_pass_confirmation_timeout(monkeypatch):
    monkeypatch.setattr(
        executor,
        "list_entries",
        lambda cfg: ["porcaria-accessible/emory.edu/tnesbi2"],
    )
    monkeypatch.setattr(
        executor,
        "run",
        lambda argv, **kwargs: Completed(124, "", "timeout after 120s"),
    )

    report = executor.run_selection(
        SecretCfg(),
        "PASS_COPY porcaria-accessible/emory.edu/tnesbi2",
    )

    assert not report.ok
    assert report.outcome is not None
    assert "timed out" in report.outcome.error
