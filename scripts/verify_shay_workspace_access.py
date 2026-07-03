#!/usr/bin/env python3
"""Verify Shay workspace access and email-verification gating.

Usage:
  python3 scripts/verify_shay_workspace_access.py \
    --email you@example.com \
    --password 'secret'

What it checks:
1. Login against Shay auth
2. Read the authenticated profile and print `is_verified`
3. Attempt workspace creation against the Shay backend directly
4. Attempt workspace creation through the Next.js proxy route

This is useful when the UI shows:
  "Please verify your email to continue."
or when workspace creation looks unauthenticated from the browser.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def request_json(
    url: str,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    data = None
    headers = {
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            body = _parse_json(raw)
            return response.status, body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        body = _parse_json(raw)
        return exc.code, body


def _parse_json(raw: str) -> dict[str, Any] | list[Any] | str:
    if not raw:
        return ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def print_step(title: str) -> None:
    print(f"\n== {title} ==")


def print_json(label: str, value: Any) -> None:
    print(f"{label}: {json.dumps(value, indent=2, sort_keys=True)}")


def extract_detail(body: Any) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        message = body.get("message")
        if isinstance(message, str):
            return message
    return json.dumps(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Shay user email")
    parser.add_argument("--password", required=True, help="Shay user password")
    parser.add_argument(
        "--backend-base",
        default="http://localhost:8090/api/v1",
        help="Direct Shay backend base URL",
    )
    parser.add_argument(
        "--proxy-base",
        default="http://localhost:3000/api/shay",
        help="Next.js proxy base URL",
    )
    parser.add_argument(
        "--workspace-name",
        default=f"Codex Verify {int(time.time())}",
        help="Temporary workspace name for create test",
    )
    parser.add_argument(
        "--resend-verification",
        action="store_true",
        help="Also trigger resend verification email",
    )
    args = parser.parse_args()

    print_step("Login")
    login_status, login_body = request_json(
        f"{args.backend_base}/user-auth/login",
        method="POST",
        payload={
            "email_id": args.email,
            "password": args.password,
            "encrypted": False,
        },
    )
    print(f"status: {login_status}")
    print_json("body", login_body)
    if login_status != 200 or not isinstance(login_body, dict):
        print("\nLogin failed, stopping.")
        return 1

    token = login_body.get("access_token")
    company_id = login_body.get("company_id")
    if not isinstance(token, str) or not token:
        print("\nNo access_token returned, stopping.")
        return 1

    print_step("Profile")
    profile_status, profile_body = request_json(
        f"{args.backend_base}/user-auth/profile",
        token=token,
    )
    print(f"status: {profile_status}")
    print_json("body", profile_body)

    is_verified = None
    if isinstance(profile_body, dict):
        is_verified = profile_body.get("is_verified")
        print(f"is_verified: {is_verified}")

    if args.resend_verification:
        print_step("Resend Verification Email")
        resend_status, resend_body = request_json(
            f"{args.backend_base}/public/resend-verification",
            method="POST",
            payload={
                "email": args.email,
                "platform_name": "Aryx",
            },
        )
        print(f"status: {resend_status}")
        print_json("body", resend_body)

    workspace_payload = {
        "name": args.workspace_name,
        "description": "Verification script test",
        "workspace_type": "aryx",
        "is_public": False,
        "ai_enabled": True,
        "ai_provider": "openai",
        "ai_model": "gpt-4",
    }

    print_step("Create Workspace Direct Backend")
    direct_status, direct_body = request_json(
        f"{args.backend_base}/workspaces/",
        method="POST",
        token=token,
        payload=workspace_payload,
    )
    print(f"status: {direct_status}")
    print_json("body", direct_body)

    print_step("Create Workspace Via Next Proxy")
    proxy_status, proxy_body = request_json(
        f"{args.proxy_base}/workspaces/",
        method="POST",
        token=token,
        payload=workspace_payload,
    )
    print(f"status: {proxy_status}")
    print_json("body", proxy_body)

    print_step("Summary")
    if is_verified is False:
        print("Profile shows is_verified=false.")
    if direct_status in (401, 403):
        print(f"Direct backend create blocked: {extract_detail(direct_body)}")
    if proxy_status in (401, 403):
        print(f"Proxy create blocked: {extract_detail(proxy_body)}")
    if is_verified is True and direct_status == 201 and proxy_status == 201:
        print("Everything passed: token and verification state both allow workspace creation.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
