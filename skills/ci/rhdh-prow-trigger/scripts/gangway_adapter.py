#!/usr/bin/env python3
"""Credential-owning OpenShift CI Gangway adapter.

The public workflow passes only a kubeconfig path and request data. This module
retrieves the native ``oc`` credential transiently, authenticates the request,
and returns credential-free response data.
"""

from __future__ import annotations

import http.client
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GANGWAY_URL = "https://gangway-ci.apps.ci.l2s4.p1.openshiftapps.com/v1/executions"
SETUP_GUIDANCE = "Run /setup-rhdh-skills openshift-ci, then retry."


class GangwayAdapterError(RuntimeError):
    """A credential-opaque failure from the Gangway adapter."""

    def __init__(
        self,
        message: str,
        *,
        outcome_unknown: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown
        # Only network failures and 5xx responses are worth another read;
        # credential, client, and response-format failures are not.
        self.retryable = retryable


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
            raise GangwayAdapterError(f"Cannot run oc. {SETUP_GUIDANCE}") from error
        token = result.stdout.strip()
        if result.returncode != 0 or not token:
            raise GangwayAdapterError(
                f"OpenShift CI authentication is missing or expired. {SETUP_GUIDANCE}"
            )
        return token

    def _request(
        self, url: str, *, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        is_post = method == "POST"
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
                guidance = f"Authentication was rejected. {SETUP_GUIDANCE}"
            elif error.code == 403:
                guidance = "Permission denied. Ask an OpenShift CI administrator to check access."
            elif error.code == 400:
                guidance = "Invalid request. Check the job name, execution ID, and overrides."
            elif error.code == 404:
                # Live Gangway answers 500, not 404, for unknown execution IDs, so a
                # mistyped --status ID usually lands in the 5xx branch below.
                guidance = (
                    "Execution not found. Check the execution ID."
                    if not is_post
                    else "Job or endpoint not found. Check the configured job list and Gangway URL."
                )
            elif error.code == 408:
                guidance = "Gangway timed out. Check OpenShift CI service availability."
            elif error.code == 429:
                guidance = "Rate limit exceeded. Wait before retrying."
            elif error.code >= 500:
                guidance = (
                    "Gangway service failure, or an unknown execution ID. "
                    "Check the execution ID and OpenShift CI service availability."
                    if not is_post
                    else "Gangway service failure. Check OpenShift CI service availability."
                )
            else:
                guidance = "Check the request and OpenShift CI service availability."
            raise GangwayAdapterError(
                f"Gangway returned HTTP {error.code}. {guidance}",
                outcome_unknown=is_post and (error.code == 408 or error.code >= 500),
                retryable=error.code >= 500,
            ) from error
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            # HTTPException covers IncompleteRead and BadStatusLine: the connection
            # dropped mid-response, so a POST may already have created the job.
            raise GangwayAdapterError(
                "Gangway network request failed. Check DNS, network/VPN connectivity, "
                "and OpenShift CI service availability.",
                outcome_unknown=is_post,
                retryable=True,
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise GangwayAdapterError(
                "Gangway returned an invalid JSON response. Check OpenShift CI service availability.",
                outcome_unknown=is_post,
            ) from error
        if not isinstance(body, dict):
            raise GangwayAdapterError(
                "Gangway returned an unexpected response; expected a JSON object.",
                outcome_unknown=is_post,
            )
        return body

    def trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(GANGWAY_URL, method="POST", payload=payload)

    def status(self, job_id: str) -> dict[str, Any]:
        return self._request(f"{GANGWAY_URL}/{urllib.parse.quote(job_id, safe='')}")
