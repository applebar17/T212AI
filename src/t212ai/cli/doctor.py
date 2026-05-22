from __future__ import annotations

import argparse

from t212ai.app.bootstrap import assess_settings, preflight_run_bot, run_provider_smoke_tests

from .common import _configure_app_logging, load_settings_from_cli
from .reports import render_doctor_report


def command_doctor(args: argparse.Namespace) -> int:
    settings = load_settings_from_cli(env_file=args.env_file)
    _configure_app_logging(settings)
    assessment = assess_settings(settings)
    preflight = preflight_run_bot(assessment)
    smoke_results = run_provider_smoke_tests(settings, assessment) if args.smoke else None
    print(render_doctor_report(settings, assessment, preflight, smoke_results=smoke_results))
    return 0 if assessment.is_valid else 1
