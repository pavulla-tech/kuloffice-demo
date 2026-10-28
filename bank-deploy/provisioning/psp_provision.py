#!/usr/bin/env python3
"""Provision a PSP partner (a bank's cash deposits and transfers) without bypassing production gates.

One provisioner for every partner: the FNB pilot (fnb-pilot.example.yaml) and,
on dev, the PSP simulator playing the partner bank (simulator-bank.example.yaml).
Each partner's YAML says who it is, its evidence and what it needs enabled.

The command is deliberately resumable. Non-secret progress is stored in
state.json and one-time credentials in secrets.json (0600). Re-running apply
adopts what already exists and continues from the first unmet gate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import http.cookies
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the provisioner image
    yaml = None


class ProvisionError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ProvisionError(f"{path} must contain a JSON object")
    return value


def nested(data: dict[str, Any], dotted: str, default: Any = None) -> Any:
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def require(config: dict[str, Any], fields: list[str]) -> None:
    missing = [name for name in fields if nested(config, name) in (None, "", [])]
    if missing:
        raise ProvisionError("configuration is missing required values: " + ", ".join(missing))


def load_config(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise ProvisionError("PyYAML is not installed in the provisioner image")
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ProvisionError("the pilot YAML must contain an object")
    if value.get("schema_version") != 1:
        raise ProvisionError("schema_version must be 1")
    # Relative evidence paths resolve beside the YAML. The wrapper mounts that
    # whole directory read-only, so the same input folder is portable.
    for name in ("partner.commercial_terms.signed_contract_file", "partner.statement_profile.sample_file",
                 "partner.certification_statement_file"):
        raw = nested(value, name)
        if raw:
            target = Path(str(raw)).expanduser()
            if not target.is_absolute():
                target = path.parent / target
            container = value
            parts = name.split(".")
            for part in parts[:-1]:
                container = container[part]
            container[parts[-1]] = str(target)
    for document in nested(value, "partner.kyb.documents", []) or []:
        if isinstance(document, dict) and document.get("file"):
            target = Path(str(document["file"])).expanduser()
            if not target.is_absolute():
                target = path.parent / target
            document["file"] = str(target)
    require(value, [
        "operators.maker.email", "operators.maker.first_name", "operators.maker.last_name",
        "operators.checker.email", "operators.checker.first_name", "operators.checker.last_name",
        "operators.partner_technical.email", "operators.partner_technical.first_name", "operators.partner_technical.last_name",
        "partner.legal_name", "partner.registration_number", "partner.licence.type", "partner.licence.number",
        "partner.licence.issuer", "partner.technical_contact.name", "partner.technical_contact.email",
        "partner.compliance_contact.name", "partner.compliance_contact.email", "partner.kyb.screenings.sanctions.subject",
        "partner.kyb.screenings.sanctions.reference", "partner.kyb.screenings.pep.subject",
        "partner.kyb.screenings.pep.reference", "partner.commercial_terms.contract_ref",
        "partner.commercial_terms.signed_contract_file", "partner.statement_profile.sample_file",
        "partner.statement_profile.profile.standard", "partner.statement_profile.profile.accounts",
        "partner.commercial_terms.settlement.account",
        "test_business.business_name", "test_business.biller.code", "test_business.biller.name",
        "test_business.product.code", "test_business.product.name",
        "test_business.invoices.rf.number", "test_business.invoices.rf.account_reference",
        "test_business.invoices.rf.amount", "test_business.invoices.qr.number",
        "test_business.invoices.qr.account_reference", "test_business.invoices.qr.amount",
    ])
    maker = nested(value, "operators.maker.email").strip().lower()
    checker = nested(value, "operators.checker.email").strip().lower()
    if maker == checker:
        raise ProvisionError("maker and checker must be different people")
    for name in ("operators.maker.email", "operators.checker.email", "operators.partner_technical.email",
                 "partner.technical_contact.email", "partner.compliance_contact.email"):
        email = str(nested(value, name, "")).strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ProvisionError(f"{name} must be an email address")
    for name, low, high in (("pilot.limit_percentage", 1, 100), ("pilot.routing_weight", 1, 100),
                            ("pilot.credential_valid_days", 1, 365)):
        try:
            number = int(nested(value, name))
        except (TypeError, ValueError) as error:
            raise ProvisionError(f"{name} must be an integer") from error
        if number < low or number > high:
            raise ProvisionError(f"{name} must be between {low} and {high}")
    for name in ("partner.expected_monthly_volume",):
        try:
            if int(nested(value, name)) <= 0:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise ProvisionError(f"{name} must be a positive integer") from error
    for name in ("partner.expected_monthly_value", "partner.commercial_terms.limits.per_transaction",
                 "partner.commercial_terms.limits.daily", "partner.commercial_terms.limits.monthly",
                 "test_business.invoices.rf.amount", "test_business.invoices.qr.amount"):
        try:
            if Decimal(str(nested(value, name))) <= 0:
                raise ValueError
        except (ValueError, ArithmeticError) as error:
            raise ProvisionError(f"{name} must be a positive amount") from error
    standard = str(nested(value, "partner.statement_profile.profile.standard", "")).strip().lower()
    if standard != "csv":
        raise ProvisionError("partner.statement_profile.profile.standard must be csv for automated certification")
    matrix = nested(value, "partner.capability_matrix", {})
    types = matrix.get("types", []) if isinstance(matrix, dict) else []
    rows = {(str(row.get("type", "")).upper(), method)
            for row in types if isinstance(row, dict) for method in row.get("methods", [])}
    for needed in (("NAME_LOOKUP", "cash_deposit"), ("CASH_IN", "cash_deposit")):
        if needed not in rows:
            raise ProvisionError(f"partner.capability_matrix must enable {needed[0]}/{needed[1]}")
    capabilities = matrix.get("capabilities", []) if isinstance(matrix, dict) else []
    incoming = next((row for row in capabilities if row.get("name") == "account_funding.incoming"), None)
    if not incoming or not {"test", "live"}.issubset(set(incoming.get("modes", []))) or \
            "MZN" not in incoming.get("currencies", []):
        raise ProvisionError("partner.capability_matrix must enable account_funding.incoming in test and live for MZN")
    if not nested(value, "partner.kyb.documents"):
        raise ProvisionError("partner.kyb.documents must list every required KYB document")
    for name in ("partner.commercial_terms.signed_contract_file", "partner.statement_profile.sample_file"):
        file_path = Path(str(nested(value, name))).expanduser()
        if not file_path.is_file():
            raise ProvisionError(f"{name} does not exist: {file_path}")
    for index, document in enumerate(nested(value, "partner.kyb.documents", [])):
        if not isinstance(document, dict) or not document.get("type") or not document.get("file"):
            raise ProvisionError(f"partner.kyb.documents[{index}] needs type and file")
        if not Path(str(document["file"])).expanduser().is_file():
            raise ProvisionError(f"KYB file does not exist: {document['file']}")
    return value


def extract_one_time_key(which: str, page: str) -> str:
    environment = "test" if which == "sandbox" else "live"
    match = re.search(rf"kp_{environment}_(?:sk|rk|pk)_[0-9A-Za-z]{{49}}", html.unescape(page))
    if not match:
        raise ProvisionError(f"Gateway did not return the one-time {which} key")
    return match.group(0)


# The launch-matrix routes a partner needs live, unless its YAML lists its own
# (partner.launch_routes): the FNB pilot's cash deposits.
DEFAULT_LAUNCH_ROUTES = [{"operation": "cash_deposit", "driver": "partner_api", "method": "cash", "mode": "live", "scope": "acc_top"}]


def launch_routes(config: dict[str, Any]) -> list[dict[str, str]]:
    return nested(config, "partner.launch_routes", None) or DEFAULT_LAUNCH_ROUTES


def missing_routes(matrix: dict[str, Any], wanted: list[dict[str, str]]) -> list[dict[str, str]]:
    """The wanted routes the Gateway's matrix in force does not enable (its
    /admin/launch-matrix answer lists one route per operation, driver,
    method, mode and scope)."""
    routes = matrix.get("routes", matrix.get("matrix", {}).get("routes", []))
    def enabled(want: dict[str, str]) -> bool:
        return any(route.get("enabled") is True and all(route.get(k) == v for k, v in want.items()) for route in routes)
    return [want for want in wanted if not enabled(want)]


def route_text(route: dict[str, str]) -> str:
    return "/".join(str(route.get(k, "")) for k in ("operation", "driver", "method", "mode", "scope"))


def live_cash_deposit_enabled(matrix: dict[str, Any]) -> bool:
    return not missing_routes(matrix, DEFAULT_LAUNCH_ROUTES)


def percentage_amount(value: str, percentage: int) -> str:
    """Return a two-decimal pilot limit without binary floating-point drift."""
    return str((Decimal(str(value)) * Decimal(percentage) / Decimal(100)).quantize(Decimal("0.01")))


def statement_payments(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The payments a failed statement case says the bank's statement must list.

    The Gateway names them as "listing: REF AMOUNT CURRENCY; ..." when no
    statement was uploaded, and as "missing: REF AMOUNT, ..." when the
    uploaded one did not list them.
    """
    case = next((c for c in cases if c.get("kind") == "statement" and c.get("status") == "failed"), None)
    if case is None:
        return []
    actual = str(case.get("actual", ""))
    payments: list[dict[str, str]] = []
    if "listing: " in actual:
        for item in actual.split("listing: ", 1)[1].split(";"):
            parts = item.split()
            if len(parts) >= 2:
                payments.append({"reference": parts[0], "amount": parts[1],
                                 "currency": parts[2] if len(parts) > 2 else "MZN"})
    elif "missing: " in actual:
        for item in actual.split("missing: ", 1)[1].split(","):
            parts = item.split()
            if len(parts) >= 2:
                payments.append({"reference": parts[0], "amount": parts[1], "currency": "MZN"})
    return payments


def failed_cases_other_than_statement(cases: list[dict[str, Any]]) -> list[str]:
    return [str(c.get("key")) for c in cases
            if c.get("status") == "failed" and c.get("mandatory") and c.get("kind") != "statement"]


class HTTP:
    def __init__(self, base: str, key: str = "") -> None:
        self.base = base.rstrip("/")
        self.key = key

    def call(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None,
             expected: tuple[int, ...] = (200, 201, 202)) -> tuple[int, Any, dict[str, str]]:
        request_headers = {"Accept": "application/json"}
        if self.key:
            request_headers["Authorization"] = "Bearer " + self.key
        if headers:
            request_headers.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                result = json.loads(raw) if raw and "json" in response.headers.get("Content-Type", "") else raw.decode(errors="replace")
                if response.status not in expected:
                    raise ProvisionError(f"{method} {path}: unexpected HTTP {response.status}")
                return response.status, result, dict(response.headers)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:2000]
            raise ProvisionError(f"{method} {path} failed: HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ProvisionError(f"{method} {path} failed: {error.reason}") from error

    def multipart(self, path: str, fields: dict[str, str], files: dict[str, Path],
                  expected: tuple[int, ...] = (200, 201, 202), method: str = "POST") -> Any:
        boundary = "----kulpay-" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks += [f"--{boundary}\r\n".encode(),
                       f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                       str(value).encode(), b"\r\n"]
        for name, path_value in files.items():
            content_type = mimetypes.guess_type(path_value.name)[0] or "application/octet-stream"
            chunks += [f"--{boundary}\r\n".encode(),
                       f'Content-Disposition: form-data; name="{name}"; filename="{path_value.name}"\r\n'.encode(),
                       f"Content-Type: {content_type}\r\n\r\n".encode(), path_value.read_bytes(), b"\r\n"]
        chunks.append(f"--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.base + path, data=b"".join(chunks), method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                if response.status not in expected:
                    raise ProvisionError(f"{method} {path}: unexpected HTTP {response.status}")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:2000]
            raise ProvisionError(f"{method} {path} failed: HTTP {error.code}: {detail}") from error


class Provisioner:
    def __init__(self, config: dict[str, Any], output: Path, dry_run: bool = False) -> None:
        self.config = config
        # The partner's short name in reasons, keys and messages ("FNB").
        self.name = str(nested(config, "partner.short_name", "") or nested(config, "partner.legal_name", "")).strip()
        self.output = output
        self.dry_run = dry_run
        self.state_path = output / "state.json"
        self.secrets_path = output / "secrets.json"
        self.report_path = output / "readiness-report.json"
        self.state = read_json(self.state_path)
        self.secret_values = read_json(self.secrets_path)
        management = os.environ.get("GATEWAY_MANAGEMENT_URL", "http://gateway:9091/v1")
        public = os.environ.get("GATEWAY_PUBLIC_INTERNAL_URL", "http://gateway:9090")
        self.admin = HTTP(management, os.environ.get("GATEWAY_ADMIN_KEY", ""))
        self.checker = HTTP(management, os.environ.get("GATEWAY_CHECKER_KEY", ""))
        self.public = HTTP(public)

    def save(self) -> None:
        if self.dry_run:
            return
        atomic_json(self.state_path, self.state)
        atomic_json(self.secrets_path, self.secret_values)

    def step(self, message: str) -> None:
        log(("PLAN  " if self.dry_run else "== ") + message)

    def require_runtime(self, include_keycloak: bool = True) -> None:
        names = ["GATEWAY_ADMIN_KEY", "GATEWAY_CHECKER_KEY"]
        if include_keycloak and nested(self.config, "operators.create_workforce_users", True):
            names.extend(("KC_ADMIN_PASSWORD", "GATEWAY_OIDC_CLIENT_SECRET", "GATEWAY_MGMT_PUBLIC_URL"))
        for name in names:
            if not os.environ.get(name, "").strip():
                raise ProvisionError(f"{name} is required in the deployment environment")
        if os.environ["GATEWAY_ADMIN_KEY"] == os.environ["GATEWAY_CHECKER_KEY"]:
            raise ProvisionError("GATEWAY_ADMIN_KEY and GATEWAY_CHECKER_KEY must differ")

    def keycloak_call(self, method: str, path: str, token: str = "", body: Any = None,
                      form: dict[str, str] | None = None) -> tuple[int, Any]:
        base = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
        headers: dict[str, str] = {}
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode(errors="replace")

    def ensure_users(self) -> None:
        if not nested(self.config, "operators.create_workforce_users", True):
            return
        self.step("create or reuse workforce users")
        if self.dry_run:
            return
        status, token_doc = self.keycloak_call("POST", "/realms/master/protocol/openid-connect/token", form={
            "grant_type": "password", "client_id": "admin-cli",
            "username": os.environ.get("KC_ADMIN_USER", "admin"), "password": os.environ["KC_ADMIN_PASSWORD"],
        })
        if status != 200:
            raise ProvisionError(f"Keycloak admin login failed: HTTP {status}")
        token = token_doc["access_token"]
        realm = os.environ.get("WORKFORCE_REALM", "workforce")
        client_result = subprocess.run(["python3", "/tools/gateway_admin_client.py"], env=os.environ.copy(),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if client_result.returncode != 0:
            raise ProvisionError("could not create or update the Gateway workforce client")
        client_id = os.environ.get("GATEWAY_OIDC_CLIENT_ID", "kulpay-gateway-admin")
        status, clients = self.keycloak_call("GET", f"/admin/realms/{realm}/clients?" +
                                             urllib.parse.urlencode({"clientId": client_id}), token)
        if status != 200 or not isinstance(clients, list) or not clients:
            raise ProvisionError(f"Gateway workforce client {client_id} was not found after provisioning")
        gateway_client_uuid = clients[0]["id"]
        passwords = self.secret_values.setdefault("workforce_temporary_passwords", {})
        for role in ("maker", "checker", "partner_technical"):
            person = nested(self.config, f"operators.{role}")
            email = person["email"].strip().lower()
            query = urllib.parse.urlencode({"email": email, "exact": "true"})
            status, users = self.keycloak_call("GET", f"/admin/realms/{realm}/users?{query}", token)
            if status != 200:
                raise ProvisionError(f"could not find workforce user {email}: HTTP {status}")
            reused = bool(users)
            password = ""
            if not reused:
                password = passwords.get(email) or secrets.token_urlsafe(18)
                passwords[email] = password
                # Persist before the external write. A retry can then recover
                # the temporary password if creation succeeds and this process stops.
                self.save()
            command_env = os.environ.copy()
            command_env.update({
                "KC_BOOTSTRAP_ADMIN_USERNAME": os.environ.get("KC_ADMIN_USER", "admin"),
                "KC_BOOTSTRAP_ADMIN_PASSWORD": os.environ["KC_ADMIN_PASSWORD"],
                "STAFF_EMAIL": email, "STAFF_FIRST_NAME": person["first_name"],
                "STAFF_LAST_NAME": person["last_name"],
                "KULOFFICE_ROLE": str(person.get("kuloffice_role", "")),
                "GATEWAY_OPERATOR": "1" if person.get("gateway_operator", False) else "0",
                "SOLANGE_ROLES": ",".join(person.get("solange_roles", []) or []),
            })
            if password:
                command_env["STAFF_PASSWORD"] = password
            result = subprocess.run(["/tools/operator.sh"], env=command_env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, check=False)
            if result.returncode != 0:
                # Deliberately do not echo output: the helper can print a
                # one-time password. The address identifies the failed step.
                raise ProvisionError(f"could not provision workforce access for {email}")
            status, users = self.keycloak_call("GET", f"/admin/realms/{realm}/users?{query}", token)
            if status != 200 or not users:
                raise ProvisionError(f"workforce helper completed but {email} was not found")
            gateway_operator = False
            if person.get("gateway_operator", False):
                status, roles = self.keycloak_call(
                    "GET", f"/admin/realms/{realm}/users/{users[0]['id']}/role-mappings/clients/{gateway_client_uuid}", token)
                gateway_operator = status == 200 and isinstance(roles, list) and any(
                    role.get("name") == "operator" for role in roles)
                if not gateway_operator:
                    raise ProvisionError(f"Gateway operator role was not granted to {email}")
            self.state.setdefault("workforce_users", {})[role] = {
                "id": users[0]["id"], "email": email, "reused": reused,
                "kuloffice_role": person.get("kuloffice_role", ""),
                "gateway_operator": gateway_operator,
                "solange_roles": person.get("solange_roles", []) or [],
            }
            self.save()
        self.save()

    def approve(self, approval_id: str, reason: str) -> None:
        if not approval_id:
            raise ProvisionError("Gateway did not return an approval id")
        self.checker.call("POST", f"/admin/approvals/{approval_id}/decide", {"approve": True, "reason": reason})

    def pending_approval(self, subject_id: str, kind: str, config_kind: str = "") -> str:
        _, body, _ = self.admin.call("GET", "/admin/approvals?" + urllib.parse.urlencode({
            "subject_id": subject_id, "pending": "1",
        }))
        def matches(row: dict[str, Any]) -> bool:
            if row.get("kind") != kind:
                return False
            if not config_kind:
                return True
            try:
                payload = json.loads(row.get("payload", "{}"))
            except (TypeError, json.JSONDecodeError):
                return False
            return payload.get("kind") == config_kind
        item = next((row for row in body.get("data", []) if matches(row)), None)
        return item.get("id", "") if item else ""

    def accounts(self) -> list[dict[str, Any]]:
        _, body, _ = self.admin.call("GET", "/admin/accounts")
        return body.get("data", [])

    def ensure_test_business(self) -> None:
        self.step("create or reuse pilot business, biller, product and invoices")
        if self.dry_run:
            return
        business_name = nested(self.config, "test_business.business_name")
        account = next((item for item in self.accounts() if item.get("business_name") == business_name), None)
        if account is None:
            _, created, _ = self.admin.call("POST", "/admin/accounts", {
                "business_name": business_name,
                "country": nested(self.config, "test_business.country", "MZ"),
                "status": "active",
            })
            account = created["account"]
        self.state["test_business_account_id"] = account["id"]

        biller_cfg = nested(self.config, "test_business.biller")
        code = biller_cfg["code"].upper()
        try:
            _, current, _ = self.admin.call("GET", f"/admin/billers/{code}")
            biller = current["biller"]
            products = current.get("products", [])
        except ProvisionError as error:
            if "HTTP 404" not in str(error):
                raise
            payload = dict(biller_cfg)
            payload["tenant_id"] = account["id"]
            _, biller, _ = self.admin.call("POST", "/admin/billers", payload)
            products = []
        if biller.get("tenant_id") != account["id"]:
            raise ProvisionError(f"biller code {code} belongs to another account; choose a unique pilot biller code")
        self.state["biller_id"] = biller["id"]

        product_cfg = dict(nested(self.config, "test_business.product"))
        product_code = product_cfg["code"].upper()
        if not any(item.get("code") == product_code for item in products):
            self.admin.call("POST", f"/admin/billers/{code}/products", product_cfg)

        if biller.get("status") != "active":
            approval_id = self.pending_approval(biller["id"], "bill.biller_status")
            if not approval_id:
                _, prepared, _ = self.admin.call("POST", f"/admin/billers/{code}/status", {
                    "status": "active", "reason": f"Enable controlled {self.name} pilot biller",
                })
                approval_id = prepared["approval"]["id"]
            self.approve(approval_id, f"Approve controlled {self.name} pilot biller")

        biller_key = self.secret_values.get("test_biller_api_key", "")
        if not biller_key:
            _, issued, _ = self.admin.call("POST", f"/admin/accounts/{account['id']}/keys", {
                "name": f"{self.name} pilot invoice presenter", "type": "sk",
                "scopes": ["invoices:read", "invoices:write"],
            })
            biller_key = issued["key"]["secret"]
            self.secret_values["test_biller_api_key"] = biller_key
            self.state["test_biller_api_key_id"] = issued["key"].get("id")
            self.state["test_biller_api_key_expires_at"] = issued["key"].get("expires_at")
            self.save()
        biller_api = HTTP(os.environ.get("GATEWAY_PUBLIC_INTERNAL_URL", "http://gateway:9090/v1"), biller_key)
        if not biller_api.base.endswith("/v1"):
            biller_api.base += "/v1"
        today = dt.date.today()
        invoices = []
        for kind in ("rf", "qr"):
            item = dict(nested(self.config, f"test_business.invoices.{kind}"))
            item.update({"currency": nested(self.config, "deployment.currency", "MZN"),
                         "issue_date": today.isoformat(), "due_date": (today + dt.timedelta(days=30)).isoformat()})
            invoices.append(item)
        biller_api.call("POST", "/biller/invoices", {"invoices": invoices})
        artifacts: dict[str, Any] = {}
        for kind, item in zip(("rf", "qr"), invoices):
            _, invoice, _ = biller_api.call("GET", "/biller/invoices/" + urllib.parse.quote(item["number"], safe=""))
            artifacts[kind] = invoice
        self.state["test_invoices"] = artifacts
        self.save()

    def application_data(self) -> dict[str, Any]:
        partner = self.config["partner"]
        licence = {key: value for key, value in partner["licence"].items() if value}
        return {
            "kind": "psp", "partner_type": partner.get("partner_type", "bank"),
            "legal_name": partner["legal_name"], "registration_number": partner["registration_number"],
            "country": nested(self.config, "deployment.country", "MZ"), "licences": [licence],
            "roles": ["cash_deposit_bank"], "countries": [nested(self.config, "deployment.country", "MZ")],
            "currencies": [nested(self.config, "deployment.currency", "MZN")],
            "transaction_types": ["cash_deposit", "bill_payment"],
            "expected_monthly_volume": partner["expected_monthly_volume"],
            "expected_monthly_value": {"amount": str(partner["expected_monthly_value"]),
                                       "currency": nested(self.config, "deployment.currency", "MZN")},
            "technical_contact": partner["technical_contact"], "compliance_contact": partner["compliance_contact"],
            "language": nested(self.config, "deployment.language", "pt"),
        }

    def ensure_application(self) -> None:
        self.step(f"create or resume {self.name} PSP application")
        if self.dry_run:
            return
        if self.state.get("psp_id"):
            return
        _, listed, _ = self.admin.call("GET", "/admin/psps")
        existing = next((item for item in listed.get("data", []) if item.get("legal_name") == self.config["partner"]["legal_name"]), None)
        if existing:
            if not self.secret_values.get("application_draft_token"):
                raise ProvisionError(
                    f"an {self.name} PSP already exists but its one-time application token is not in the output directory; "
                    "restore the original provisioning output directory before resuming")
            self.state["psp_id"] = existing["id"]
            self.state["application_id"] = existing.get("application_id", "")
            self.save()
            return
        _, app, _ = self.public.call("POST", "/v1/psps/applications", self.application_data())
        app_id, draft_token = app["id"], app["draft_token"]
        _, submitted, _ = self.public.call("POST", f"/v1/psps/applications/{app_id}/submit", headers={
            "KulPay-Application-Token": draft_token,
        })
        self.state.update({"application_id": app_id, "psp_id": submitted["psp_id"]})
        self.secret_values["application_draft_token"] = draft_token
        self.save()

    def psp(self) -> dict[str, Any]:
        _, body, _ = self.admin.call("GET", f"/admin/psps/{self.state['psp_id']}")
        return body.get("psp", body)

    def transition(self, target: str, reason: str) -> None:
        psp = self.psp()
        if psp.get("status") == target:
            return
        self.admin.call("POST", f"/admin/psps/{psp['id']}/transitions", {"to": target, "reason": reason})

    def ensure_kyb(self) -> None:
        self.step("complete KYB with maker/checker approval")
        if self.dry_run:
            return
        psp = self.psp()
        if psp.get("kyb_status") == "approved":
            return
        if psp.get("status") == "applied":
            self.transition("kyb_review", f"Start {self.name} KYB review")
        _, kyb, _ = self.admin.call("GET", f"/admin/psps/{psp['id']}/kyb")
        existing_docs = {(item.get("type"), item.get("filename")): item for item in kyb.get("documents", [])}
        for document in nested(self.config, "partner.kyb.documents"):
            path = Path(str(document["file"])).expanduser()
            current = existing_docs.get((document["type"], path.name))
            if current is None:
                current = self.admin.multipart(f"/admin/psps/{psp['id']}/kyb/documents",
                                               {"type": document["type"]}, {"file": path})
            if current.get("status") != "accepted":
                self.admin.call("POST", f"/admin/psps/{psp['id']}/kyb/documents/{current['id']}/review",
                                {"decision": "accepted", "comment": f"Verified for {self.name} pilot"})
        existing_kinds = {item.get("kind") for item in kyb.get("screenings", []) if item.get("result") == "clear"}
        for kind in ("sanctions", "pep"):
            if kind in existing_kinds:
                continue
            item = nested(self.config, f"partner.kyb.screenings.{kind}")
            self.admin.call("POST", f"/admin/psps/{psp['id']}/kyb/screenings", {
                "kind": kind, "subject": item["subject"], "result": "clear",
                "reference": item["reference"], "notes": item.get("notes", ""),
            })
        self.admin.call("POST", f"/admin/psps/{psp['id']}/kyb/risk-tier", {
            "tier": nested(self.config, "partner.risk_tier", "medium"), "reason": f"{self.name} pilot risk assessment",
        })
        approval_id = self.pending_approval(psp["id"], "psp.kyb.approve")
        if not approval_id:
            _, prepared, _ = self.admin.call("POST", f"/admin/psps/{psp['id']}/kyb/decision", {
                "decision": "approve", "reason": f"{self.name} KYB evidence reviewed",
            })
            approval_id = prepared["approval"]["id"]
        self.approve(approval_id, f"Approve {self.name} KYB for controlled pilot")
        self.save()

    def ensure_commercial(self) -> None:
        self.step("approve commercial terms and register signed contract")
        if self.dry_run:
            return
        psp = self.psp()
        if psp.get("status") == "kyb_approved":
            self.transition("commercial_setup", f"Begin {self.name} commercial setup")
            psp = self.psp()
        _, versions, _ = self.admin.call("GET", f"/admin/psps/{psp['id']}/configs?kind=commercial_terms")
        if not any(item.get("status") == "active" for item in versions.get("data", [])):
            terms = dict(nested(self.config, "partner.commercial_terms"))
            contract_file = Path(str(terms.pop("signed_contract_file"))).expanduser()
            approval_id = self.pending_approval(psp["id"], "config.activate", "commercial_terms")
            if not approval_id:
                _, prepared, _ = self.admin.call("POST", f"/admin/psps/{psp['id']}/configs/commercial_terms", {
                    "document": terms, "reason": f"{self.name} pilot commercial terms",
                })
                approval_id = prepared["approval"]["id"]
            self.approve(approval_id, f"Approve {self.name} pilot commercial terms")
            self.admin.multipart(f"/admin/psps/{psp['id']}/contract", {"reason": f"Signed {self.name} pilot contract"}, {"file": contract_file})
        elif not psp.get("contract_signed"):
            contract_file = Path(str(nested(self.config, "partner.commercial_terms.signed_contract_file"))).expanduser()
            self.admin.multipart(f"/admin/psps/{psp['id']}/contract", {"reason": f"Signed {self.name} pilot contract"}, {"file": contract_file})
        self.save()

    def ensure_capabilities(self) -> None:
        self.step(f"approve {self.name} capability matrix")
        if self.dry_run:
            return
        psp_id = self.state["psp_id"]
        _, versions, _ = self.admin.call("GET", f"/admin/psps/{psp_id}/configs?kind=capability_matrix")
        if any(item.get("status") == "active" for item in versions.get("data", [])):
            return
        approval_id = self.pending_approval(psp_id, "config.activate", "capability_matrix")
        if not approval_id:
            _, prepared, _ = self.admin.call("POST", f"/admin/psps/{psp_id}/configs/capability_matrix", {
                "document": nested(self.config, "partner.capability_matrix"),
                "reason": f"{self.name} cash-deposit capability for controlled pilot",
            })
            approval_id = prepared["approval"]["id"]
        self.approve(approval_id, f"Approve {self.name} cash-deposit capability")
        self.save()

    def reveal_onboarding_key(self, which: str) -> str:
        saved = self.secret_values.get(which + "_api_key", "")
        if saved:
            return saved
        app_id = self.state.get("application_id", "")
        token = self.secret_values.get("application_draft_token", "")
        if not app_id or not token:
            raise ProvisionError(f"cannot reveal {which} key: application draft token is unavailable")
        base = os.environ.get("GATEWAY_PUBLIC_INTERNAL_URL", "http://gateway:9090").rstrip("/")
        application_cookie = f"kulpay_psp_application={app_id}.{token}"
        page_request = urllib.request.Request(base + "/onboarding", method="GET", headers={"Cookie": application_cookie})
        try:
            with urllib.request.urlopen(page_request, timeout=60) as response:
                set_cookies = response.headers.get_all("Set-Cookie") or []
                response.read()
        except urllib.error.HTTPError as error:
            raise ProvisionError(f"could not establish onboarding session: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise ProvisionError(f"could not establish onboarding session: {error.reason}") from error
        csrf = ""
        for raw_cookie in set_cookies:
            parsed = http.cookies.SimpleCookie()
            parsed.load(raw_cookie)
            if "kulpay_csrf" in parsed:
                csrf = parsed["kulpay_csrf"].value
        if not csrf:
            raise ProvisionError("Gateway did not issue the onboarding CSRF cookie")
        request = urllib.request.Request(base + f"/onboarding/{which}-key", data=b"", method="POST", headers={
            "Cookie": application_cookie + "; kulpay_csrf=" + csrf,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                page = response.read().decode(errors="replace")
        except urllib.error.HTTPError as error:
            raise ProvisionError(f"could not reveal {which} key: HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise ProvisionError(f"could not reveal {which} key: {error.reason}") from error
        token_value = extract_one_time_key(which, page)
        self.secret_values[which + "_api_key"] = token_value
        self.save()
        return token_value

    def ensure_statement_profile(self, psp_key: str) -> None:
        self.step(f"validate and install {self.name} statement profile")
        if self.dry_run:
            return
        psp_id = self.state["psp_id"]
        partner = self.partner_api(psp_key)
        try:
            _, current, _ = partner.call("GET", f"/psps/{psp_id}/statement-profiles")
            if current.get("profiles"):
                self.state["statement_profile_id"] = current["profiles"][0]["id"]
                self.save()
                return
        except ProvisionError as error:
            if "HTTP 404" not in str(error):
                raise
        profile = dict(nested(self.config, "partner.statement_profile.profile"))
        sample_path = Path(str(nested(self.config, "partner.statement_profile.sample_file"))).expanduser()
        preview = partner.multipart(f"/psps/{psp_id}/statement-profiles/preview",
                                    {"profile": json.dumps(profile)}, {"sample": sample_path})
        profile["sample_file_id"] = preview["sample_file_id"]
        partner.call("PUT", f"/psps/{psp_id}/statement-profiles", {
            "profiles": [profile], "reason": f"{self.name} cash-deposit reconciliation profile",
        })
        self.state["statement_profile_id"] = profile["id"]
        self.save()

    def partner_api(self, key: str) -> "HTTP":
        return HTTP(os.environ.get("GATEWAY_PUBLIC_INTERNAL_URL", "http://gateway:9090").rstrip("/") + "/v1", key)

    def ensure_webhook_endpoint(self, mode: str, key: str) -> None:
        """Registers the partner's webhook endpoint for a mode, once.

        The certification's webhook cases sign and send real webhooks to the
        test endpoint; the live one receives the pilot's. The signing secret
        is shown once: it is kept in secrets.json and, for the simulator bank,
        handed to the simulator.
        """
        url = str(nested(self.config, f"partner.webhooks.{mode}_url", "") or "").strip()
        if not url:
            return
        self.step(f"register {self.name} {mode} webhook endpoint")
        if self.dry_run:
            return
        api = self.partner_api(key)
        _, listed, _ = api.call("GET", "/webhook-endpoints")
        rows = listed.get("data", []) if isinstance(listed, dict) else []
        if any(row.get("url") == url and not row.get("disabled_at") for row in rows):
            if not self.secret_values.get(f"{mode}_webhook_secret"):
                log(f"WARN  the {mode} webhook endpoint exists but its secret is not in secrets.json; rotate it in the portal")
            return
        body: dict[str, Any] = {"url": url, "mode": mode}
        events = nested(self.config, "partner.webhooks.event_types")
        if events:
            body["event_types"] = list(events)
        _, created, _ = api.call("POST", "/webhook-endpoints", body)
        self.secret_values[f"{mode}_webhook_secret"] = created["secret"]
        self.state[f"{mode}_webhook_endpoint_id"] = created.get("id")
        self.save()

    def simulator(self) -> "HTTP | None":
        """The PSP simulator when it plays the partner bank (dev only)."""
        url = str(nested(self.config, "simulator.url", "") or "").strip()
        return HTTP(url) if url else None

    def hand_to_simulator(self, mode: str, key: str) -> None:
        simulator = self.simulator()
        if simulator is None:
            return
        self.step(f"hand the simulator its {mode} partner key and webhook secret")
        if self.dry_run:
            return
        body = {"gateway_key": key, "mode": mode,
                "statement_profile_id": self.state.get("statement_profile_id", "")}
        if self.secret_values.get(f"{mode}_webhook_secret"):
            body["webhook_secret"] = self.secret_values[f"{mode}_webhook_secret"]
        simulator.call("PUT", "/api/partner/setup", body)

    def certification_statement(self, payments: list[dict[str, str]]) -> Path | None:
        """The bank's statement for a failed statement case.

        The simulator bank produces it at once. A real bank is asked for it:
        the list goes to statement-request.json, and its statement is named in
        partner.certification_statement_file for the next apply.
        """
        path = self.output / "certification-statement.csv"
        simulator = self.simulator()
        if simulator is not None:
            _, csv_text, _ = simulator.call("POST", "/api/partner/certification-statement", {"payments": payments})
            path.write_text(csv_text if isinstance(csv_text, str) else str(csv_text))
            return path
        given = str(nested(self.config, "partner.certification_statement_file", "") or "").strip()
        if given and Path(given).expanduser().is_file():
            return Path(given).expanduser()
        atomic_json(self.output / "statement-request.json", {
            "columns": ["reference", "amount", "currency", "date"], "payments": payments,
            "note": f"{self.name} lists these sandbox payments in a CSV statement; "
                    "name it in partner.certification_statement_file and run apply again",
        }, mode=0o644)
        return None

    def start_run(self, rerun_of: str = "", statement: Path | None = None) -> dict[str, Any]:
        psp_id = self.state["psp_id"]
        fields = {"rerun_of": rerun_of} if rerun_of else {}
        if statement is None and not rerun_of:
            statement = Path(str(nested(self.config, "partner.statement_profile.sample_file"))).expanduser()
        if statement is None:
            _, run, _ = self.admin.call("POST", f"/admin/psps/{psp_id}/certification/runs", {"rerun_of": rerun_of})
            return run
        return self.admin.multipart(f"/admin/psps/{psp_id}/certification/runs", fields, {"statement": statement})

    def wait_run(self, run_id: str) -> dict[str, Any]:
        psp_id = self.state["psp_id"]
        deadline = time.monotonic() + 35 * 60
        while time.monotonic() < deadline:
            _, view, _ = self.admin.call("GET", f"/admin/psps/{psp_id}/certification/runs/{run_id}")
            if view["run"].get("status") != "running":
                self.state["certification_run"] = view["run"]
                self.save()
                return view
            time.sleep(5)
        raise ProvisionError("certification did not finish within 35 minutes")

    def ensure_certification(self) -> bool:
        """Runs certification in rounds until it passes or waits on someone.

        Round 1 runs every case with the sample statement. A failed statement
        case names the run's sandbox payments; with the bank's statement
        listing them, round 2 repeats the failed cases and carries the passed
        ones (and their payments). Any other failed mandatory case waits for
        the partner's integration to be corrected; the next apply repeats the
        failed cases.
        """
        self.step("run Gateway certification and stop if any mandatory case fails")
        if self.dry_run:
            return False
        psp_id = self.state["psp_id"]
        psp = self.psp()
        if psp.get("certified_at"):
            return True
        if psp.get("status") == "commercial_setup":
            self.transition("technical_setup", f"Open {self.name} sandbox technical setup")
        sandbox_key = self.reveal_onboarding_key("sandbox")
        self.ensure_statement_profile(sandbox_key)
        self.ensure_webhook_endpoint("test", sandbox_key)
        self.hand_to_simulator("test", sandbox_key)
        psp = self.psp()
        if psp.get("status") == "technical_setup":
            self.transition("certification", f"Begin {self.name} cash-deposit certification")
        _, runs, _ = self.admin.call("GET", f"/admin/psps/{psp_id}/certification/runs")
        latest = next(iter(runs.get("data", [])), None)
        # A run that failed before this apply is repeated once: the partner
        # may have corrected its integration since.
        resumed = False
        if latest is not None and latest.get("status") == "running":
            view = self.wait_run(latest["id"])
        elif latest is not None and latest.get("status") == "failed":
            _, view, _ = self.admin.call("GET", f"/admin/psps/{psp_id}/certification/runs/{latest['id']}")
            resumed = True
        else:
            view = self.wait_run(self.start_run()["id"])
        for _ in range(3):
            if view["run"].get("status") == "passed":
                return bool(self.psp().get("certified_at"))
            payments = statement_payments(view.get("cases", []))
            statement = None
            if payments:
                statement = self.certification_statement(payments)
                if statement is None:
                    log(f"WAIT  {self.name}'s statement must list {len(payments)} sandbox payment(s): "
                        f"see {self.output / 'statement-request.json'}")
                    return False
            elif not resumed:
                break
            resumed = False
            log("==    repeat the failed cases" + (" with the bank's statement" if statement else ""))
            view = self.wait_run(self.start_run(rerun_of=view["run"]["id"], statement=statement)["id"])
        if view["run"].get("status") == "passed":
            return bool(self.psp().get("certified_at"))
        failed = failed_cases_other_than_statement(view.get("cases", [])) or ["statement/sample"]
        log(f"WAIT  certification did not pass ({', '.join(failed)}); inspect readiness-report.json "
            f"and run apply again after {self.name}'s integration is corrected")
        return False

    def ensure_pilot(self) -> None:
        self.step("enter controlled pilot, set limits and restrict merchants")
        if self.dry_run:
            return
        psp = self.psp()
        if psp.get("status") != "pilot":
            self.transition("pilot", nested(self.config, "pilot.reason"))
            psp = self.psp()
        terms = nested(self.config, "partner.commercial_terms.limits")
        percentage = int(nested(self.config, "pilot.limit_percentage", 10))
        merchants = [self.state["test_business_account_id"]]
        self.admin.call("PUT", f"/admin/psps/{psp['id']}/pilot", {
            "per_transaction": percentage_amount(terms["per_transaction"], percentage),
            "daily": percentage_amount(terms["daily"], percentage),
            "monthly": percentage_amount(terms["monthly"], percentage), "currency": terms["currency"],
            "merchants": merchants, "routing_weight": int(nested(self.config, "pilot.routing_weight", 10)),
            "reason": nested(self.config, "pilot.reason"),
        })
        # The Gateway necessarily issues a full secret key on entering pilot.
        # Replace it immediately with the least-privilege restricted key the partner
        # needs for the agreed flows, then revoke the broad one.
        broad_key = self.reveal_onboarding_key("live")
        broad_api = self.partner_api(broad_key)
        if not self.secret_values.get("partner_live_api_key"):
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                days=int(nested(self.config, "pilot.credential_valid_days", 90)))
            _, issued, _ = broad_api.call("POST", "/api-keys", {
                "name": f"{self.name} controlled cash-deposit pilot", "type": "rk",
                "scopes": ["transactions:read", "transactions:write", "bills:read", "bills:artifacts",
                           "events:read", "reconciliation:read", "reconciliation:write"],
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
            })
            self.secret_values["partner_live_api_key"] = issued["secret"]
            self.state["partner_live_api_key_id"] = issued["id"]
            self.state["partner_live_api_key_expires_at"] = issued.get("expires_at")
            self.state["partner_live_key_restricted"] = True
            self.save()
        # The live webhook endpoint is registered while the broad key exists:
        # the restricted key has no webhook scope.
        self.ensure_webhook_endpoint("live", broad_key)
        broad_id = psp.get("live_key_id", "")
        if broad_id and not self.state.get("broad_pilot_key_revoked"):
            broad_api.call("DELETE", f"/api-keys/{broad_id}", expected=(200, 204))
            self.state["broad_pilot_key_revoked"] = True
            self.secret_values.pop("live_api_key", None)
        self.save()
        self.hand_to_simulator("live", self.secret_values["partner_live_api_key"])

    def rollback(self) -> int:
        """Disable pilot traffic and suspend the partner through maker/checker.

        No PSP, API key, approval, or audit record is deleted. Removing the
        merchant allow-list first makes the pilot ineligible for new routing;
        suspension then blocks the account and all of its credentials.
        """
        self.require_runtime(include_keycloak=False)
        self.step(f"disable {self.name} pilot routing and suspend the PSP")
        if not self.state.get("psp_id"):
            _, listed, _ = self.admin.call("GET", "/admin/psps")
            match = next((item for item in listed.get("data", [])
                          if item.get("legal_name") == self.config["partner"]["legal_name"]), None)
            if match is None:
                raise ProvisionError(f"{self.name} PSP was not found; nothing can be rolled back")
            self.state["psp_id"] = match["id"]
            self.save()

        psp = self.psp()
        if psp.get("status") == "suspended":
            self.state["pilot_routing_disabled"] = True
            self.save()
            self.report("pilot_suspended")
            return 0
        if psp.get("status") != "pilot":
            raise ProvisionError(f"rollback expects {self.name} in pilot or suspended, not {psp.get('status')}")

        terms = nested(self.config, "partner.commercial_terms.limits")
        percentage = int(nested(self.config, "pilot.limit_percentage", 10))
        reason = nested(self.config, "pilot.rollback_reason", f"Disable {self.name} pilot and preserve audit trail")
        self.admin.call("PUT", f"/admin/psps/{psp['id']}/pilot", {
            "per_transaction": percentage_amount(terms["per_transaction"], percentage),
            "daily": percentage_amount(terms["daily"], percentage),
            "monthly": percentage_amount(terms["monthly"], percentage),
            "currency": terms["currency"], "merchants": [], "routing_weight": 1,
            "reason": reason,
        })
        self.state["pilot_routing_disabled"] = True
        self.save()

        approval_id = self.pending_approval(psp["id"], "psp.suspend")
        if not approval_id:
            _, prepared, _ = self.admin.call("POST", f"/admin/psps/{psp['id']}/suspension", {
                "reason": reason, "emergency": False,
            })
            approval_id = prepared["approval"]["id"]
        self.approve(approval_id, f"Approve controlled {self.name} pilot suspension")
        suspended = self.psp()
        if suspended.get("status") != "suspended":
            raise ProvisionError(f"Gateway accepted the approval but {self.name} is not suspended")
        self.state["suspended_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.save()
        self.report("pilot_suspended")
        return 0

    def verify_launch_matrix(self) -> None:
        self.step("verify the partner's live routes in the launch matrix")
        if self.dry_run:
            return
        _, matrix, _ = self.admin.call("GET", "/admin/launch-matrix")
        missing = missing_routes(matrix, launch_routes(self.config))
        self.state["launch_routes_enabled"] = not missing
        self.state["launch_matrix_version"] = matrix.get("version") or matrix.get("matrix", {}).get("version")
        self.save()
        if missing:
            raise ProvisionError("the active launch matrix does not enable " + ", ".join(route_text(r) for r in missing))

    def report(self, outcome: str) -> None:
        report = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "outcome": outcome,
            "psp_id": self.state.get("psp_id"), "application_id": self.state.get("application_id"),
            "test_business_account_id": self.state.get("test_business_account_id"),
            "statement_profile_id": self.state.get("statement_profile_id"),
            "launch_matrix_version": self.state.get("launch_matrix_version"),
            "live_cash_deposit_route_enabled": self.state.get("live_cash_deposit_route_enabled", False),
            "certification": self.state.get("certification_run"),
            "test_invoices": self.state.get("test_invoices", {}),
            "partner_live_api_key_id": self.state.get("partner_live_api_key_id"),
            "partner_live_api_key_expires_at": self.state.get("partner_live_api_key_expires_at"),
            "partner_live_api_key_scopes": ["transactions:read", "transactions:write", "bills:read",
                                         "bills:artifacts", "events:read", "reconciliation:read",
                                         "reconciliation:write"],
            "test_webhook_endpoint_id": self.state.get("test_webhook_endpoint_id"),
            "live_webhook_endpoint_id": self.state.get("live_webhook_endpoint_id"),
            "pilot_routing_disabled": self.state.get("pilot_routing_disabled", False),
            "suspended_at": self.state.get("suspended_at"),
            "credentials_file": str(self.secrets_path),
        }
        if not self.dry_run:
            atomic_json(self.report_path, report)
        log(f"RESULT {outcome}; report: {self.report_path}")

    def apply(self) -> int:
        self.require_runtime()
        self.verify_launch_matrix()
        self.ensure_users()
        self.ensure_test_business()
        self.ensure_application()
        self.ensure_kyb()
        self.ensure_commercial()
        self.ensure_capabilities()
        if not self.ensure_certification():
            self.report("waiting_for_certification")
            return 3
        self.ensure_pilot()
        self.report("pilot_ready")
        return 0

    def plan(self) -> int:
        self.require_runtime()
        _, matrix, _ = self.admin.call("GET", "/admin/launch-matrix")
        missing = missing_routes(matrix, launch_routes(self.config))
        if missing:
            raise ProvisionError("the active launch matrix does not enable " + ", ".join(route_text(r) for r in missing))
        self.admin.call("GET", "/admin/accounts")
        self.checker.call("GET", "/admin/approvals?pending=1")
        simulator = self.simulator()
        if simulator is not None:
            simulator.call("GET", "/healthz")
        if nested(self.config, "operators.create_workforce_users", True):
            status, _ = self.keycloak_call("POST", "/realms/master/protocol/openid-connect/token", form={
                "grant_type": "password", "client_id": "admin-cli",
                "username": os.environ.get("KC_ADMIN_USER", "admin"), "password": os.environ["KC_ADMIN_PASSWORD"],
            })
            if status != 200:
                raise ProvisionError(f"Keycloak admin login failed during preflight: HTTP {status}")
        for action in (self.verify_launch_matrix, self.ensure_users, self.ensure_test_business, self.ensure_application,
                       self.ensure_kyb, self.ensure_commercial, self.ensure_capabilities, self.ensure_certification,
                       self.ensure_pilot):
            action()
        self.report("plan_valid")
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply", "rollback"))
    parser.add_argument("--config", default=os.environ.get("PSP_CONFIG", os.environ.get("FNB_PILOT_CONFIG", "/config/psp.yaml")))
    parser.add_argument("--output", default=os.environ.get("PSP_OUTPUT", os.environ.get("FNB_PILOT_OUTPUT", "/output")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(Path(args.config))
        provisioner = Provisioner(config, Path(args.output), dry_run=args.command == "plan")
        if args.command == "plan":
            return provisioner.plan()
        if args.command == "rollback":
            return provisioner.rollback()
        return provisioner.apply()
    except ProvisionError as error:
        log("ERROR " + str(error))
        return 2
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        log("ERROR provisioning input or runtime failed: " + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
