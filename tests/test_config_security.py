import os
import subprocess
import sys


def run_config_import(environment, secret):
    env = os.environ.copy()
    env.pop("QR_PUBLIC_TOKEN_SECRET", None)
    if secret is not None:
        env["QR_PUBLIC_TOKEN_SECRET"] = secret
    env["ENVIRONMENT"] = environment
    return subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
    )


def test_missing_qr_secret_is_rejected_in_production():
    result = run_config_import("production", None)

    assert result.returncode != 0
    assert "QR_PUBLIC_TOKEN_SECRET must be configured in production" in (
        result.stderr + result.stdout
    )


def test_development_can_use_local_qr_secret_fallback():
    result = run_config_import("development", None)

    assert result.returncode == 0


def test_production_accepts_explicit_qr_secret():
    result = run_config_import("production", "test-only-strong-secret")

    assert result.returncode == 0
