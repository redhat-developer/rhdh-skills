#!/usr/bin/env python3
"""Credential-owning OpenShift CI Gangway adapter.

The public workflow passes only a kubeconfig path and request data. This module
retrieves the native ``oc`` credential transiently, authenticates the request,
and returns credential-free response data.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GANGWAY_URL = "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions"


class GangwayAdapterError(RuntimeError):
    """A credential-opaque failure from the Gangway adapter."""

    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


class GangwayAdapter:
    """Authenticate and execute Gangway requests behind a credential-free interface."""

    def __init__(self, kubeconfig: str, *, executable: str = "oc") -> None:
        self.kubeconfig = kubeconfig
        self.executable = executable

    def _token(self) -> str:
        try:
            result = subprocess.run(
                [self.executable, "--kubeconfig", self.kubeconfig, "whoami", "-t"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
            )
        except OSError as error:
            raise GangwayAdapterError(
                "Cannot run oc. Run /setup-rhdh-skills openshift-ci, then retry."
            ) from error
        token = result.stdout.strip()
        if result.returncode != 0 or not token:
            raise GangwayAdapterError(
                "OpenShift CI authentication is missing or expired. "
                "Run /setup-rhdh-skills openshift-ci, then retry."
            )
        return token

    def _request(
        self, url: str, *, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "User-Agent": "rhdh-skills",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 401:
                guidance = (
                    "Authentication was rejected. Run /setup-rhdh-skills openshift-ci, then retry."
                )
            elif error.code == 403:
                guidance = "Permission denied. Ask an OpenShift CI administrator to check access."
            elif error.code == 400:
                guidance = "Invalid request. Check the job name, execution ID, and overrides."
            elif error.code == 404:
                guidance = (
                    "Execution not found. Check the execution ID."
                    if method == "GET"
                    else "Job or endpoint not found. Check the configured job list and Gangway URL."
                )
            elif error.code == 429:
                guidance = "Rate limit exceeded. Wait before retrying."
            elif error.code >= 500:
                guidance = "Gangway service failure. Check OpenShift CI service availability."
            else:
                guidance = "Check the request and OpenShift CI service availability."
            raise GangwayAdapterError(
                f"Gangway returned HTTP {error.code}. {guidance}",
                outcome_unknown=method == "POST" and (error.code == 408 or error.code >= 500),
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise GangwayAdapterError(
                "Gangway network request failed. Check DNS, network/VPN connectivity, "
                "and OpenShift CI service availability.",
                outcome_unknown=method == "POST",
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise GangwayAdapterError(
                "Gangway returned an invalid JSON response. Check OpenShift CI service availability.",
                outcome_unknown=method == "POST",
            ) from error
        if not isinstance(body, dict):
            raise GangwayAdapterError(
                "Gangway returned an unexpected response; expected a JSON object.",
                outcome_unknown=method == "POST",
            )
        return body

    def trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(GANGWAY_URL, method="POST", payload=payload)

    def status(self, job_id: str) -> dict[str, Any]:
        return self._request(f"{GANGWAY_URL}/{urllib.parse.quote(job_id, safe='')}")
