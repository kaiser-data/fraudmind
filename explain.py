#!/usr/bin/env python3
"""LLM explanation layer over deterministic findings (stdlib only).

Reads build/findings.json (produced by checks.py), asks OpenAI for
auditor-language DE/EN explanations per finding via strict structured
output, and writes build/explanations.json.

Hard rule: the LLM never decides numbers. Every numeric token in its
output is validated against the source finding; explanations containing
unknown figures are marked validated=false and the unknown numbers listed.

Run: python3 explain.py [FINDING_ID ...]   (no args = all findings)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
MODEL = "gpt-4.1-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MAX_RETRIES = 5
# The hackathon key rejects concurrent bursts with quota-style 429s while
# sequential paced calls pass - so: one request at a time, with a gap.
REQUEST_GAP_SECONDS = 21.0

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline_de": {"type": "string"},
        "headline_en": {"type": "string"},
        "explanation_de": {"type": "string"},
        "explanation_en": {"type": "string"},
        "recommended_action_de": {"type": "string"},
        "recommended_action_en": {"type": "string"},
    },
    "required": ["headline_de", "headline_en", "explanation_de",
                 "explanation_en", "recommended_action_de",
                 "recommended_action_en"],
}

SYSTEM_PROMPT = (
    "You are a senior German financial-statement auditor drafting "
    "workpaper language for findings produced by a deterministic "
    "control-testing engine over a GDPdU dossier.\n"
    "Rules:\n"
    "1. Use ONLY the amounts, dates, document numbers, account numbers "
    "and user IDs given in the finding. NEVER introduce a figure that is "
    "not in the input - the engine decides numbers, you decide wording.\n"
    "2. German text in professional Pruefungssprache (HGB/IDW register); "
    "English in equivalent audit register (ISA terminology).\n"
    "3. Headlines: one sentence. Explanations: 2-4 sentences stating the "
    "condition, the criteria violated, and the effect. Recommended action: "
    "1-2 sentences of concrete next audit steps.\n"
    "4. State facts as the engine found them; do not soften a CRITICAL "
    "finding, do not escalate a NEEDS_REVIEW item beyond its evidence."
)


def load_api_key() -> str:
    env_file = ROOT / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')
    key = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY missing (.env or env)")
    return key


def numeric_tokens(text: str) -> set[str]:
    """Digit sequences (3+ digits) with separators stripped: '295.120,00' -> '29512000'."""
    tokens = set()
    for match in re.findall(r"\d[\d.,]*\d|\d{3,}", text):
        digits = re.sub(r"\D", "", match)
        if len(digits) >= 3:
            tokens.add(digits)
    return tokens


def source_blob(finding: dict) -> str:
    parts = [finding.get("title", ""), finding.get("explanation", ""),
             " ".join(finding.get("provenance", [])), finding.get("id", "")]
    amount = finding.get("amount_eur")
    if amount is not None:
        parts.append(f"{amount} {amount:.2f} {amount:,.2f}")
    return " ".join(parts)


def validate_numbers(finding: dict, texts: list[str]) -> list[str]:
    known = numeric_tokens(source_blob(finding))
    # Substring match: '295120' in source covers '295.120,00 EUR' in output
    # (trailing cents make the output token '29512000').
    unknown = []
    for token in sorted(set().union(*(numeric_tokens(t) for t in texts))):
        stripped = token.rstrip("0") or token
        if not any(stripped in k or k in token for k in known):
            unknown.append(token)
    return unknown


def build_payload(finding: dict, mode: str) -> dict:
    """mode 'json_schema' = strict structured output; 'json_object' =
    fallback when the account's structured-output quota flag rejects
    strict mode (the key-list is then enforced client-side instead)."""
    system = SYSTEM_PROMPT
    if mode == "json_object":
        response_format = {"type": "json_object"}
        system += ("\n5. Respond with a JSON object containing exactly "
                   "these string keys and no others: "
                   + ", ".join(SCHEMA["required"]) + ".")
    else:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "audit_explanation", "strict": True,
                            "schema": SCHEMA},
        }
    return {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(finding, ensure_ascii=False)},
        ],
        "response_format": response_format,
        "temperature": 0.2,
        # cap output: with max_tokens unset, OpenAI reserves the model's
        # full output limit against remaining quota -> 429 on low balances
        "max_tokens": 900,
    }


def openai_explain(api_key: str, finding: dict) -> dict:
    headers = {"Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}
    mode = "json_schema"
    for attempt in range(MAX_RETRIES):
        data = json.dumps(build_payload(finding, mode)).encode()
        req = urllib.request.Request(OPENAI_URL, data=data, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.loads(r.read().decode())
            out = json.loads(body["choices"][0]["message"]["content"])
            missing = [k for k in SCHEMA["required"]
                       if not isinstance(out.get(k), str) or not out[k]]
            if missing:
                raise KeyError(f"model omitted keys: {missing}")
            return out
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            quota = "insufficient_quota" in detail
            if quota and mode == "json_schema":
                mode = "json_object"  # strict-mode quota flag: retry looser
                continue
            if e.code in (429, 500, 502, 503) and not quota \
                    and attempt < MAX_RETRIES - 1:
                retry_after = e.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2.0 * 2 ** attempt
                time.sleep(min(delay, 30.0))
                continue
            raise urllib.error.URLError(
                f"HTTP {e.code}: {detail[:200]}") from e
    raise urllib.error.URLError("retries exhausted")


def explain_finding(api_key: str, finding: dict) -> tuple[str, dict]:
    fid = finding["id"]
    try:
        out = openai_explain(api_key, finding)
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        return fid, {"error": f"{type(e).__name__}: {e}"}
    unknown = validate_numbers(finding, list(out.values()))
    result = dict(out)
    result["model"] = MODEL
    result["validated"] = not unknown
    if unknown:
        result["unknown_numbers"] = unknown
    return fid, result


def main() -> None:
    api_key = load_api_key()
    findings = json.loads((ROOT / "build" / "findings.json").read_text())
    only = set(sys.argv[1:])
    if only:
        findings = [f for f in findings if f["id"] in only]
    if not findings:
        raise SystemExit("no findings matched")

    out_path = ROOT / "build" / "explanations.json"
    existing = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text())
    if not only:  # full run: skip findings that already succeeded
        findings = [f for f in findings
                    if "error" in existing.get(f["id"], {"error": "missing"})]
        if not findings:
            print("all findings already explained")
            return

    results = {}
    for i, finding in enumerate(findings):
        if i > 0:
            time.sleep(REQUEST_GAP_SECONDS)
        fid, result = explain_finding(api_key, finding)
        results[fid] = result
        status = "error" if "error" in result else "ok"
        print(f"  [{i + 1}/{len(findings)}] {fid}: {status}", flush=True)
        merged = {**existing, **results}
        out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

    merged = {**existing, **results}

    ok = sum(1 for r in results.values() if r.get("validated"))
    flagged = [(fid, r["unknown_numbers"]) for fid, r in results.items()
               if r.get("unknown_numbers")]
    errors = [(fid, r["error"]) for fid, r in results.items() if "error" in r]
    print(f"{len(results)} explanations -> {out_path} "
          f"({ok} validated, {len(flagged)} with unknown numbers, "
          f"{len(errors)} errors)")
    for fid, nums in flagged:
        print(f"  {fid}: unknown numbers {nums}")
    for fid, err in errors:
        print(f"  {fid}: ERROR {err}")


if __name__ == "__main__":
    main()
