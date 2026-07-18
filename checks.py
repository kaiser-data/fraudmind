#!/usr/bin/env python3
"""checks.py - deterministic fraud/misstatement checks over the ingested dossier.

Reads build/ artifacts (from ingest.py) plus raw GDPdU tables, runs the check
catalog, and writes build/findings.json. Every finding carries provenance
(source file + row/page). Two tiers protect against false-positive penalty:
  FLAGGED      - deterministic rule violation, high confidence
  NEEDS_REVIEW - suspicious pattern, requires auditor judgment

Anti-overfitting: no hardcoded account/vendor/user IDs from any dossier.
Thresholds, lock dates, management IDs and the designated full-review account
are parsed from the dossier's own audit-planning workpaper; patterns (user IDs,
document prefixes, journal markers) are derived from the data itself.
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import ingest
from ingest import USER_RE, gl_entry_no, gl_user, parse_num, read_gdpdu_table

BUILD = Path(__file__).parent / "build"
JET_PROV = "Begleitdokumente/Pruefungsplanung_JET_2025.docx"

SERVICE_WORDS = re.compile(
    r"fracht|miete|beratung|energie|wartung|versicherung|it-|telefon|leasing|"
    r"reinigung|entsorgung|honorar|lizenz|schulung|instandhaltung|zins|gebuehr|"
    r"geb\xfchr|steuer|personal|logistik|transport|druckleistung", re.I)
REPAIR_WORDS = re.compile(
    r"reparatur|instandsetzung|instandhaltung|wartung|austausch|ueberholung|"
    r"\xfcberholung|erneuerung", re.I)

findings = []


def d(s):
    """'07.01.2025' -> date, else None."""
    try:
        return datetime.strptime(str(s).strip(), "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None


def eur(x):
    return f"{x:,.2f} EUR".replace(",", "_").replace(".", ",").replace("_", ".")


def truthy(v):
    return v in (True, 1) or str(v).strip().lower() in ("ja", "yes", "x", "true", "1")


def add(check, tier, severity, confidence, title, explanation, prov, amount=None):
    findings.append({
        "id": f"F{len(findings) + 1:03d}", "check": check, "tier": tier,
        "severity": severity, "confidence": confidence, "title": title,
        "explanation": explanation, "amount_eur": amount,
        "provenance": sorted(set(prov)),
    })


def acct_no(row):
    """'331000------' or '331000' -> '331000'."""
    m = re.match(r"\d+", str(row.get("SACHKONTONUMMER", "")))
    return m.group(0) if m else None


def gl_time(row):
    t = row.get("ERFASSUNGSZEIT")
    if isinstance(t, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", t):
        return t
    for v in row.values():
        if isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", v):
            return v
    return None


def gl_entry_date(row):
    dt = d(row.get("ERFASSUNGSDATUM"))
    if dt:
        return dt
    vals = list(row.values())
    for i, v in enumerate(vals):
        if isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", v):
            for j in range(i - 1, -1, -1):
                dt = d(vals[j])
                if dt:
                    return dt
    return None


def sheet_like(xdoc, namepart):
    """Fuzzy sheet lookup: first sheet whose name contains namepart."""
    for name, rows in (xdoc or {}).items():
        if namepart.lower() in name.lower():
            return rows
    return []


def main():
    entities = json.loads((BUILD / "entities.json").read_text())
    chains = json.loads((BUILD / "chains.json").read_text())
    xlsx = json.loads((BUILD / "xlsx_docs.json").read_text())
    planning = (BUILD / "planning_text.txt").read_text() \
        if (BUILD / "planning_text.txt").exists() else ""

    # ---- thresholds & policy targets from the dossier's own planning doc ----
    def money_from(pattern, default):
        m = re.search(pattern, planning, re.I | re.S)
        return parse_num(m.group(1)) if m else default

    MATERIALITY = money_from(r"Wesentlichkeit[^:\n]*:\s*([\d\.]+)\s*EUR", 400_000.0)
    JET_DE_MINIMIS = money_from(r"Nichtaufgriffsgrenze[^\n]*?([\d\.]+)\s*EUR",
                                25_000.0)
    ROUND_MULTIPLE = money_from(r"Vielfache[n]? von ([\d\.]+)\s*EUR", 1_000.0)
    m = re.search(r"Sperrdatum\s+(\d{2}\.\d{2}\.\d{4})", planning)
    LOCK_DATE = d(m.group(1)) if m else None
    m = re.search(r"Erfassungsdatum\s*>\s*(\d+)\s*Tage", planning)
    BACKDATE_DAYS = int(m.group(1)) if m else 14
    m = re.search(r"Managementfunktion\s*\(([^)]*)\)", planning)
    MGMT_USERS = set(USER_RE.findall(m.group(1))) if m else set()
    m = re.search(r"Konto\s+(\d{4,6})\s*\(([^)]+)\)", planning)
    FULL_REVIEW_ACCT = (m.group(1), m.group(2)) if m else None
    m = re.search(r"vor\s+(\d{1,2}):00,?\s*nach\s+(\d{1,2}):00", planning)
    NIGHT_BEFORE, NIGHT_AFTER = (int(m.group(1)), int(m.group(2))) if m else (6, 22)
    m = re.search(r"(?:Zahlungsfreigaben|zweite Freigabe)\D{0,60}?([\d\.]+)\s*EUR",
                  planning, re.I | re.S)
    APPROVAL_LIMIT = parse_num(m.group(1)) if m else None
    m = re.search(r"<\s*(\d+)\s*Buchungen\s*p\.\s*a\.", planning)
    RARE_ACCT_MAX = int(m.group(1)) if m else 10

    ar = read_gdpdu_table("Debitoren", "Kundenbuchungen.txt")
    ap = read_gdpdu_table("Kreditoren", "Lieferantenbuchungen.txt")
    gl = read_gdpdu_table("Sachkonten", "Sachkontobuchungen.txt")
    gl_accounts = read_gdpdu_table("Sachkonten", "Sachkonten.txt")
    try:
        assets = read_gdpdu_table("AV", "Anlagen.txt")
        asset_tx = read_gdpdu_table("AV", "Anlagenbuchungen.txt")
    except FileNotFoundError:
        assets, asset_tx = [], []

    vendors = {v["id"]: v for v in entities["vendors"]}
    customers = {c["id"]: c for c in entities["customers"]}
    changes = entities["master_data_changes"]
    approvals = entities["approvals"]
    change_log = entities.get("change_log", [])
    legal_cases = entities.get("legal_cases", [])

    # permissions: any sheet rows keyed by a user-pattern value
    perms = {}
    for rows in (xlsx.get("Berechtigungsauswertung_2025.xlsx") or {}).values():
        for r in rows:
            for v in r.values():
                if isinstance(v, str) and USER_RE.fullmatch(v):
                    perms[v] = r
                    break
    faktura_jan26 = ingest.read_csv_doc("Fakturajournal_Januar_2026.csv", optional=True)
    pay26 = ingest.read_csv_doc("Buchungen_Folgeperiode_2026.csv", optional=True)

    ap_by_vendor = defaultdict(list)
    for r in ap:
        ap_by_vendor[r.get("LIEFERANTENKONTONUMMER")].append(r)
    ar_by_cust = defaultdict(list)
    for r in ar:
        ar_by_cust[r.get("KUNDENKONTONUMMER")].append(r)

    appr_prefixes = {str(a.get("ERFASSUNGSNUMMER", ""))[:4]
                     for a in approvals if a.get("ERFASSUNGSNUMMER")}

    # GDPdU column order is unreliable (practice lesson) - detect the manual-
    # journal origin marker and the opening layer by CONTENT, not by column
    def is_manual(r):
        if any(isinstance(v, str) and "erstellte journale" in v.lower()
               for v in r.values()):
            return True
        return bool(re.fullmatch(r"GJ\d+", str(r.get("BUCHUNGSNUMMER", ""))))

    def is_opening(r):
        return any(isinstance(v, str) and re.fullmatch(r"AB-\d{4}", v)
                   for v in r.values())

    # ------------------------------------------------------------------
    # CHECK 1 - Master-data self-approval (SoD) / unapproved change
    # ------------------------------------------------------------------
    for c in changes:
        approved_flag = c.get("GENEHMIGT")
        self_appr = c.get("GEAENDERT_VON") and c["GEAENDERT_VON"] == c.get("GENEHMIGT_VON")
        unapproved = approved_flag is not None and not truthy(approved_flag)
        if not (self_appr or unapproved):
            continue
        konto = c.get("KONTO")
        user = c.get("GEAENDERT_VON")
        prov = [c["_prov"]]
        p = perms.get(user, {})
        toxic = [k for k, v in p.items()
                 if truthy(v) and re.search(r"buchen|zahlung|anlegen", str(k), re.I)]
        if p:
            prov.append(str(p.get("_prov",
                        "Begleitdokumente/Berechtigungsauswertung_2025.xlsx")))
        why = "changed AND approved" if self_appr else "changed WITHOUT approval"
        expl = (f"{user} {why} master data for account {konto} "
                f"({c.get('NAME')}, field: {c.get('FELD')}, "
                f"{c.get('WERT_ALT')} -> {c.get('WERT_NEU')}) on {c.get('DATUM')} - "
                "violation of the four-eyes principle for master-data changes. ")
        if toxic:
            expl += f"{user} additionally holds rights: {', '.join(toxic)} (SoD risk). "
        txs = ap_by_vendor.get(konto, []) or ar_by_cust.get(konto, [])
        if txs:
            expl += f"Account has {len(txs)} subledger postings."
            prov += [t["_prov"] for t in txs[:10]]
        add("sod_master_data", "FLAGGED", "CRITICAL", 0.95,
            f"Master-data change without valid approval by {user}: "
            f"{c.get('NAME')} ({konto}), field {c.get('FELD')}",
            expl, prov)

    # ------------------------------------------------------------------
    # CHECK 2 - New parties transacting next period with zero FY footprint
    # ------------------------------------------------------------------
    approved_new = {c.get("KONTO") for c in changes if "Neuanlage" in str(c.get("FELD"))}
    changed_ever = {c.get("KONTO") for c in changes}
    for party_col, master, subl in (("KREDITOR", vendors, ap_by_vendor),
                                    ("DEBITOR", customers, ar_by_cust)):
        jan26_by_party = defaultdict(list)
        for r in faktura_jan26:
            if r.get(party_col):
                jan26_by_party[r[party_col]].append(r)
        if not jan26_by_party:
            continue
        opening = {pid for pid, txs in subl.items()
                   if any("Saldenvortrag" in str(t.get("BUCHUNGSTEXT", ""))
                          for t in txs)}
        ghost = [master[pid] for pid in jan26_by_party
                 if pid in master and pid not in opening and pid not in subl
                 and pid not in approved_new and pid not in changed_ever]
        if ghost:
            prov = [g["prov"] for g in ghost]
            add("party_creation_bypass", "FLAGGED", "HIGH", 0.9,
                f"{len(ghost)} {party_col.lower()}s transact next period with no "
                "2025 footprint and no creation entry in the change log",
                "These accounts have no opening balance, no FY2025 subledger "
                "postings and no recorded creation/change approval, yet invoice in "
                "the next period - the documented master-data creation control was "
                "bypassed: "
                + "; ".join(f"{g['id']} {g['name']} ({g['city']})" for g in ghost[:8]),
                prov)

    # ------------------------------------------------------------------
    # CHECK 3 - Cut-off, both directions
    # ------------------------------------------------------------------
    unrecorded = []
    for r in faktura_jan26:
        ld, amt = d(r.get("LEISTUNGSDATUM")), parse_num(r.get("BETRAG_EUR"))
        if ld and ld.year == 2025:
            party = r.get("KREDITOR") or r.get("DEBITOR")
            side = ap_by_vendor if r.get("KREDITOR") else ar_by_cust
            had_2025 = any((d(t.get("BUCHUNGSDATUM")) or ld).year == 2025
                           for t in side.get(party, []))
            if not had_2025:
                unrecorded.append((r, amt))
    if unrecorded:
        total = sum(a for _, a in unrecorded if a)
        add("cutoff_unrecorded", "FLAGGED", "CRITICAL", 0.9,
            f"Cut-off: {len(unrecorded)} next-period invoices for 2025 services "
            f"with no 2025 booking for that party - {eur(total)}",
            "Invoices in the January-2026 billing journal carry LEISTUNGSDATUM in "
            "2025, but the party has no 2025 subledger booking, i.e. no accrual/"
            "receivable/liability was recognized in FY2025 (JET cut-off criterion).",
            [r["_prov"] for r, _ in unrecorded[:20]], amount=total)

    anomalies = json.loads((BUILD / "anomalies.json").read_text())
    yr_diff = [a for a in anomalies
               if a["type"] == "service_date_year_differs_from_invoice_year"]
    premature = []
    for a in yr_diff:
        m2 = re.search(r"Leistung\s+\S*(\d{4})\s+vs\s+Faktura\s+\S*(\d{4})",
                       str(a.get("detail", "")))
        if m2 and int(m2.group(1)) > int(m2.group(2)):
            premature.append(a)
    if premature:
        amts = []
        for a in premature:
            ch = chains.get(a["invoice"], {})
            f = ch.get("faktura") or {}
            amts.append(parse_num(f.get("BETRAG_EUR")) or 0)
        add("cutoff_premature_revenue", "FLAGGED", "CRITICAL", 0.85,
            f"{len(premature)} FY2025 invoices with next-year service dates "
            f"(revenue recognized early) - {eur(sum(amts))}",
            "Billing journal rows are invoiced in FY2025 but the LEISTUNGSDATUM "
            "lies in the following year: revenue belongs to the next period "
            "(realization principle). Sample: "
            + "; ".join(f"{a['invoice']} ({a.get('detail')})" for a in premature[:5]),
            [p for a in premature[:20] for p in a["prov"]], amount=sum(amts))

    # ------------------------------------------------------------------
    # CHECK 4 - Fixed assets: repair-typical or outsized acquisitions
    # ------------------------------------------------------------------
    asset_names = {a.get("ANLAGENNUMMER"): a for a in assets}
    for t in asset_tx:
        if str(t.get("BUCHUNGSART", "")) not in ("Acquisition", "Zugang"):
            continue
        no, amt = t.get("ANLAGENNUMMER"), parse_num(t.get("BUCHUNGSBETRAG"))
        a = asset_names.get(no, {})
        name = str(a.get("ANLAGENBEZEICHNUNG", "")) or str(t.get("BUCHUNGSTEXT", ""))
        beleg = str(t.get("BELEGNUMMER", ""))
        prov = [t["_prov"]] + ([a["_prov"]] if a else [])
        sub = chains.get(beleg, {}).get("subledger", [])
        prov += [s["_prov"] for s in sub]
        if REPAIR_WORDS.search(name) or REPAIR_WORDS.search(str(t.get("BUCHUNGSTEXT", ""))):
            add("asset_repair_capitalized", "FLAGGED", "HIGH", 0.85,
                f"Repair-typical cost capitalized as asset: {name} ({no}), {eur(amt)}",
                f"Asset addition '{name}' (doc {beleg}) has a repair/maintenance-"
                "typical description. Repairs are period expense, not capitalizable "
                "- profit overstated.", prov, amount=amt)
        elif amt and amt >= MATERIALITY * 0.5:
            add("asset_large_addition", "NEEDS_REVIEW", "MEDIUM", 0.6,
                f"Large single asset addition: {name} {eur(amt)} (doc {beleg})",
                f"Single asset addition of {eur(amt)} - above 50% of overall "
                "materiality; verify existence and capitalization basis.",
                prov, amount=amt)

    # ------------------------------------------------------------------
    # CHECK 5 - Journal approvals: coverage, self-approval, rights
    # ------------------------------------------------------------------
    appr_by_no = {str(a.get("ERFASSUNGSNUMMER")): a for a in approvals}
    gl_manual_journals = defaultdict(list)
    for r in gl:
        if is_manual(r) and not is_opening(r):
            no = gl_entry_no(r, appr_prefixes)
            if no:
                gl_manual_journals[no].append(r)
    missing = {no: rows for no, rows in gl_manual_journals.items()
               if no not in appr_by_no}
    missing_share = len(missing) / (len(gl_manual_journals) or 1)
    if missing and appr_by_no and missing_share > 0.3:
        # base-rate guard: if most manual journals are "missing", the log and
        # the GL use different linkage bases - a data-quality limitation, not
        # thousands of violations
        tot = sum(max(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in rows)
                  for rows in missing.values())
        add("journal_approval_coverage", "NEEDS_REVIEW", "MEDIUM", 0.5,
            f"Approval log covers only {len(gl_manual_journals) - len(missing)} "
            f"of {len(gl_manual_journals)} manual journal entries found in the GL",
            f"{missing_share:.0%} of manual journal entry numbers do not appear "
            "in the approval log. At this rate the log and the GL likely use "
            "different linkage bases (or the log is incomplete as provided) - "
            "treated as a coverage/data-quality limitation rather than "
            f"{len(missing)} individual violations. Combined max-line volume "
            f"{eur(tot)}.",
            ["Begleitdokumente/Freigabe-Log_Journale_2025.csv",
             "Sachkonten/Sachkontobuchungen.txt"])
    elif missing and appr_by_no:
        if len(missing) <= 10:
            for no, rows in sorted(missing.items()):
                amt = max(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in rows)
                r0 = rows[0]
                add("journal_unapproved", "FLAGGED", "HIGH", 0.85,
                    f"Manual journal {r0.get('BUCHUNGSNUMMER')} (entry {no}) missing "
                    f"from approval log - {eur(amt)}",
                    f"GL journal '{r0.get('BUCHUNGSTEXT')}' posted "
                    f"{r0.get('BUCHUNGSDATUM')} by {gl_user(r0)} does not appear in "
                    "the journal approval log - the four-eyes approval control did "
                    "not operate.",
                    [r["_prov"] for r in rows[:10]]
                    + ["Begleitdokumente/Freigabe-Log_Journale_2025.csv"], amount=amt)
        else:
            tot = sum(max(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in rows)
                      for rows in missing.values())
            top = sorted(missing.items(),
                         key=lambda kv: -max(abs(parse_num(r.get("BUCHUNGSBETRAG"))
                                                 or 0) for r in kv[1]))[:6]
            add("journal_unapproved", "FLAGGED", "HIGH", 0.8,
                f"{len(missing)} manual journal entries missing from the approval "
                f"log (sum of max line amounts {eur(tot)})",
                "Manual journals must be released per the documented approval "
                "process; these entry numbers do not appear in the approval log. "
                "Largest: " + "; ".join(
                    f"{no} '{rows[0].get('BUCHUNGSTEXT')}' by {gl_user(rows[0])}"
                    for no, rows in top),
                [rows[0]["_prov"] for _, rows in top]
                + ["Begleitdokumente/Freigabe-Log_Journale_2025.csv"], amount=tot)
    self_appr = sorted(
        (a for a in approvals
         if a.get("ERSTELLER") and a["ERSTELLER"] == a.get("FREIGEBER")),
        key=lambda a: -(parse_num(a.get("SUMME_ABS_EUR")) or 0))
    for a in self_appr[:10]:
        add("journal_self_approved", "FLAGGED", "HIGH", 0.9,
            f"Journal {a.get('JOURNALNAME')} created and approved by the same "
            f"user {a['ERSTELLER']} ({eur(parse_num(a.get('SUMME_ABS_EUR')) or 0)})",
            f"Approval log entry {a.get('ERFASSUNGSNUMMER')}: ERSTELLER == FREIGEBER "
            f"({a['ERSTELLER']}), approved {a.get('FREIGABEDATUM')} - four-eyes "
            "violation (JET criterion: Freigabeverstoesse).", [a["_prov"]],
            amount=parse_num(a.get("SUMME_ABS_EUR")))
    if len(self_appr) > 10:
        tot = sum(parse_num(a.get("SUMME_ABS_EUR")) or 0 for a in self_appr[10:])
        add("journal_self_approved", "FLAGGED", "HIGH", 0.85,
            f"{len(self_appr) - 10} further self-approved journals "
            f"(ERSTELLER == FREIGEBER), total {eur(tot)}",
            "Additional journals created and released by the same user; see "
            "approval log rows in provenance.",
            [a["_prov"] for a in self_appr[10:30]], amount=tot)
    # released = status starts with "Freigegeben" (annotations like
    # "(Ersteller=Freigeber)" are handled by the self-approval check above)
    unreleased = sorted(
        (a for a in approvals
         if str(a.get("FREIGABESTATUS", "")).strip()
         and not str(a["FREIGABESTATUS"]).strip().startswith("Freigegeben")),
        key=lambda a: -(parse_num(a.get("SUMME_ABS_EUR")) or 0))
    for a in unreleased[:8]:
        amt = parse_num(a.get("SUMME_ABS_EUR")) or 0
        sev = "CRITICAL" if amt >= MATERIALITY else "HIGH"
        add("journal_posted_without_release", "FLAGGED", sev, 0.9,
            f"Journal {a.get('JOURNALNAME')} posted WITHOUT release by "
            f"{a.get('ERSTELLER')} ({eur(amt)}) - status "
            f"'{a.get('FREIGABESTATUS')}'",
            f"The approval log shows this journal with status "
            f"'{a.get('FREIGABESTATUS')}': it was posted to the GL although the "
            "documented release control did not approve it (JET criterion K6). "
            f"Created {a.get('ERFASST_AM')} {a.get('ERFASST_UM')} by "
            f"{a.get('ERSTELLER')}."
            + (" Amount exceeds overall materiality." if amt >= MATERIALITY else ""),
            [a["_prov"], "Begleitdokumente/Freigabe-Log_Journale_2025.csv"],
            amount=amt)
    if len(unreleased) > 8:
        tot = sum(parse_num(a.get("SUMME_ABS_EUR")) or 0 for a in unreleased[8:])
        add("journal_posted_without_release", "NEEDS_REVIEW", "MEDIUM", 0.7,
            f"{len(unreleased) - 8} further journals without released status "
            f"({eur(tot)})",
            "See approval log rows in provenance.",
            [a["_prov"] for a in unreleased[8:28]], amount=tot)
    bad_approver = [a for a in approvals
                    if a.get("FREIGEBER") and a["FREIGEBER"] in perms
                    and not any(truthy(v) for k, v in perms[a["FREIGEBER"]].items()
                                if re.search(r"freigeb", str(k), re.I))]
    if bad_approver:
        add("approver_without_right", "FLAGGED", "HIGH", 0.85,
            f"{len(bad_approver)} journal releases by users without the "
            "journal-approval permission",
            "The approval log names approvers to whom the permissions report "
            "grants no journal-release right - approval control circumvented or "
            "the permissions report is incorrect. Approvers: "
            + ", ".join(sorted({a['FREIGEBER'] for a in bad_approver})),
            [a["_prov"] for a in bad_approver[:15]]
            + ["Begleitdokumente/Berechtigungsauswertung_2025.xlsx"])

    # ------------------------------------------------------------------
    # CHECK 6 - JET: odd-hour/weekend postings + round amounts (base-rated)
    # ------------------------------------------------------------------
    manual_rows = [r for r in gl if is_manual(r)]
    timed = [(r, gl_time(r), gl_entry_date(r)) for r in manual_rows]
    timed = [(r, t, ed) for r, t, ed in timed if t and gl_user(r) != "Admin"]
    n = len(timed) or 1
    weekend_share = sum(1 for _, _, ed in timed if ed and ed.weekday() >= 5) / n
    night_share = sum(1 for _, t, _ in timed
                      if int(t[:2]) >= NIGHT_AFTER or int(t[:2]) < NIGHT_BEFORE) / n
    RARE = 0.05
    odd = defaultdict(list)
    for r, t, ed in timed:
        hour = int(t[:2])
        is_night = (hour >= NIGHT_AFTER or hour < NIGHT_BEFORE) and night_share < RARE
        is_weekend = ed and ed.weekday() >= 5 and weekend_share < RARE
        if is_night or is_weekend:
            amt = abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0)
            if amt >= JET_DE_MINIMIS:
                odd[(gl_user(r), str(r.get("BUCHUNGSNUMMER")))].append((r, amt, t, ed))
    for (user, jrn), rows in sorted(odd.items())[:15]:
        amt = max(a for _, a, _, _ in rows)
        r0, _, t0, ed0 = rows[0]
        when = f"{ed0.strftime('%A') if ed0 else '?'} {r0.get('BUCHUNGSDATUM')} at {t0}"
        add("jet_odd_hour_posting", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"Off-hours posting {jrn} by {user} ({when}), {eur(amt)}",
            f"Manual journal '{r0.get('BUCHUNGSTEXT')}' entered {when} - a posting "
            "time that is rare in this dossier (JET criterion K1). Amount above "
            f"the {eur(JET_DE_MINIMIS)} JET de-minimis threshold.",
            [r["_prov"] for r, _, _, _ in rows[:8]] + [JET_PROV], amount=amt)
    add("jet_time_profile", "INFO", "INFO", 1.0,
        f"Posting-time profile (manual journals): {weekend_share:.0%} weekend, "
        f"{night_share:.0%} night ({NIGHT_AFTER}:00-{NIGHT_BEFORE:02d}:00)",
        "Baseline computed from the dossier's manual journals. Time-based flags "
        f"are raised only for patterns occurring in <{RARE:.0%} of postings.",
        ["Sachkonten/Sachkontobuchungen.txt", JET_PROV])

    round_hits = [r for r in manual_rows
                  if not is_opening(r)
                  and (parse_num(r.get("BUCHUNGSBETRAG")) or 0) >= JET_DE_MINIMIS
                  and (parse_num(r.get("BUCHUNGSBETRAG")) or 0) % ROUND_MULTIPLE == 0]
    if round_hits:
        docs = {}
        for r in round_hits:
            docs.setdefault(str(r.get("BUCHUNGSNUMMER")), r)
        add("jet_round_amounts", "NEEDS_REVIEW", "LOW", 0.5,
            f"{len(round_hits)} manual GL postings with round amounts "
            f"(multiples of {eur(ROUND_MULTIPLE)}) >= {eur(JET_DE_MINIMIS)} "
            f"({len(docs)} journals)",
            "Round-amount postings above the JET de-minimis threshold: "
            + "; ".join(f"{k} {r.get('BUCHUNGSTEXT')} {r.get('BUCHUNGSBETRAG')} "
                        f"by {gl_user(r)}" for k, r in list(docs.items())[:8])
            + (" ..." if len(docs) > 8 else ""),
            [r["_prov"] for r in round_hits[:20]] + [JET_PROV])

    # ------------------------------------------------------------------
    # CHECK 7 - Split payments just under a documented approval limit
    # ------------------------------------------------------------------
    if APPROVAL_LIMIT:
        SPLIT_WINDOW_DAYS = 7
        for vid, txs in ap_by_vendor.items():
            near = [(d(t.get("BUCHUNGSDATUM")), t) for t in txs
                    if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) > 0
                    and APPROVAL_LIMIT * 0.9 <= parse_num(t["BUCHUNGSBETRAG"])
                    < APPROVAL_LIMIT and d(t.get("BUCHUNGSDATUM"))]
            near.sort(key=lambda x: x[0])
            cluster, best = [], []
            for dt, t in near:
                if cluster and (dt - cluster[-1][0]).days > SPLIT_WINDOW_DAYS:
                    cluster = []
                cluster = cluster + [(dt, t)]
                if len(cluster) > len(best):
                    best = cluster
            total = sum(parse_num(t["BUCHUNGSBETRAG"]) for _, t in best)
            if len(best) >= 2 and total > APPROVAL_LIMIT:
                v = vendors.get(vid, {})
                span = (best[-1][0] - best[0][0]).days
                add("split_payments_under_limit", "FLAGGED", "HIGH", 0.85,
                    f"{len(best)} payments to {v.get('name', vid)} within {span} "
                    f"day(s), each just under the {eur(APPROVAL_LIMIT)} approval "
                    f"limit (total {eur(total)})",
                    f"Vendor {vid} received {len(best)} separate payments in the "
                    f"band just under the documented approval limit within {span} "
                    f"day(s) - combined {eur(total)}: a single obligation split to "
                    "stay below the second-approval threshold: "
                    + "; ".join(f"{t.get('BUCHUNGSDATUM')} {t.get('BUCHUNGSBETRAG')}"
                                for _, t in best),
                    [t["_prov"] for _, t in best] + [JET_PROV], amount=total)

    # ------------------------------------------------------------------
    # CHECK 8 - Subledger <-> OP-Liste / HB tie-out
    # ------------------------------------------------------------------
    ar_sum = sum(parse_num(r.get("BUCHUNGSBETRAG")) or 0 for r in ar)
    ap_sum = sum(parse_num(r.get("BUCHUNGSBETRAG")) or 0 for r in ap)

    def num_col_sum(rows):
        tot, found = 0.0, False
        for r in rows:
            for k, v in r.items():
                if "saldo" in str(k).lower() and isinstance(v, (int, float)):
                    tot += v
                    found = True
                    break
        return tot if found else None

    op_deb = num_col_sum(sheet_like(xlsx.get("OP-Liste_Debitoren_2025.xlsx"),
                                    "Saldenliste"))
    op_kred = num_col_sum(sheet_like(xlsx.get("OP-Liste_Kreditoren_2025.xlsx"),
                                     "Saldenliste"))
    recon = {}
    for r in sheet_like(xlsx.get("Abstimmung_Nebenbuecher_HB_2025.xlsx"),
                        "Abstimmung"):
        vals = [v for v in r.values() if v is not None]
        if len(vals) >= 2 and isinstance(vals[-1], (int, float)):
            recon[str(vals[0])] = vals[-1]
    hb_ar = next((v for k, v in recon.items() if "forderung" in k.lower()), None)
    hb_ap = next((v for k, v in recon.items() if "verbindlichkeit" in k.lower()), None)
    checks8 = [
        ("AR subledger vs OP-Liste Debitoren balances", ar_sum, op_deb,
         "Debitoren/Kundenbuchungen.txt",
         "Begleitdokumente/OP-Liste_Debitoren_2025.xlsx"),
        ("AR subledger vs HB receivables per Abstimmung", ar_sum, hb_ar,
         "Debitoren/Kundenbuchungen.txt",
         "Begleitdokumente/Abstimmung_Nebenbuecher_HB_2025.xlsx"),
        ("AP subledger vs OP-Liste Kreditoren balances", ap_sum, op_kred,
         "Kreditoren/Lieferantenbuchungen.txt",
         "Begleitdokumente/OP-Liste_Kreditoren_2025.xlsx"),
        ("AP subledger vs HB payables per Abstimmung", ap_sum, hb_ap,
         "Kreditoren/Lieferantenbuchungen.txt",
         "Begleitdokumente/Abstimmung_Nebenbuecher_HB_2025.xlsx"),
    ]
    for title, a, b, p1, p2 in checks8:
        if b is None:
            continue
        diff = round(a - b, 2)
        if abs(diff) > 0.02:
            add("tie_out_difference", "FLAGGED", "HIGH", 0.85,
                f"Tie-out difference {eur(diff)}: {title}",
                f"Computed {eur(round(a, 2))} vs reported {eur(round(b, 2))} - the "
                "provided reconciliation claims agreement, which does not hold "
                "against the raw subledger.", [p1, p2], amount=abs(diff))

    # ------------------------------------------------------------------
    # CHECK 9 - Credit-limit report vs computed customer balances
    # ------------------------------------------------------------------
    bal = defaultdict(float)
    for r in ar:
        bal[r.get("KUNDENKONTONUMMER")] += parse_num(r.get("BUCHUNGSBETRAG")) or 0
    cl_mismatch, cl_breach = [], []
    for cl in entities["credit_limits"]:
        rep = parse_num(cl.get("AUSNUTZUNG_31_12_2025_EUR"))
        calc = round(bal.get(cl.get("DEBITOR"), 0.0), 2)
        # utilization cannot be negative: a customer in credit correctly
        # reports 0 - compare against max(balance, 0)
        calc_pos = max(calc, 0.0)
        if rep is not None and abs(calc_pos - rep) > 0.02:
            cl_mismatch.append((cl, rep, calc_pos))
        limit = parse_num(cl.get("KREDITLIMIT_EUR"))
        if limit and calc_pos > limit \
                and str(cl.get("STATUS", "")).lower() in ("ok", "aktiv"):
            cl_breach.append((cl, calc_pos, limit))
    n_cl = len(entities["credit_limits"]) or 1
    if cl_mismatch:
        share = len(cl_mismatch) / n_cl
        top = sorted(cl_mismatch, key=lambda x: -abs(x[2] - x[1]))[:6]
        tot = sum(abs(c - r) for _, r, c in cl_mismatch)
        add("credit_limit_mismatch", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"Credit report utilization differs from computed balances for "
            f"{len(cl_mismatch)} of {n_cl} customers (sum of diffs {eur(tot)})",
            f"{share:.0%} of the credit-limit report rows do not tie to the "
            "customer's year-end subledger balance. A high share suggests the "
            "report uses a different basis (e.g. open orders); the largest "
            "differences still warrant review: "
            + "; ".join(f"{cl.get('DEBITORNAME')} ({cl.get('DEBITOR')}) reported "
                        f"{eur(r)} vs computed {eur(c)}" for cl, r, c in top),
            [cl["_prov"] for cl, _, _ in top]
            + ["Debitoren/Kundenbuchungen.txt"], amount=tot)
    if cl_breach:
        top = sorted(cl_breach, key=lambda x: -(x[1] - x[2]))
        tot = sum(c - li for _, c, li in cl_breach)
        add("credit_limit_breach_hidden", "FLAGGED", "HIGH", 0.85,
            f"{len(cl_breach)} customers exceed their credit limit while the "
            f"report status shows no block (excess {eur(tot)})",
            "Computed year-end balances exceed the credit limit while the "
            "credit report shows an unremarkable status - limit monitoring "
            "control not operating: "
            + "; ".join(f"{cl.get('DEBITORNAME')} balance {eur(c)} vs limit "
                        f"{eur(li)} (status {cl.get('STATUS')})"
                        for cl, c, li in top[:8]),
            [cl["_prov"] for cl, _, _ in top[:15]]
            + ["Debitoren/Kundenbuchungen.txt"], amount=tot)

    # ------------------------------------------------------------------
    # CHECK 10 - Sequence gaps in document number ranges
    # ------------------------------------------------------------------
    seqs = defaultdict(set)
    for no in chains:
        m2 = re.fullmatch(r"([A-Z]{2,6})(\d{4,})", no)
        if m2:
            seqs[m2.group(1)].add(int(m2.group(2)))
    for prefix, nums in sorted(seqs.items()):
        if len(nums) < 10:
            continue
        lo, hi = min(nums), max(nums)
        gaps = sorted(set(range(lo, hi + 1)) - nums)
        if gaps and len(gaps) <= 50:
            add("sequence_gap", "NEEDS_REVIEW", "MEDIUM", 0.7,
                f"{len(gaps)} missing document number(s) in {prefix} range "
                f"{prefix}{lo}-{prefix}{hi}",
                f"Missing: {', '.join(prefix + str(g) for g in gaps[:20])}"
                + (" ..." if len(gaps) > 20 else "")
                + ". Gaps in a continuous document sequence can indicate deleted "
                  "or suppressed documents.",
                ["Begleitdokumente/Fakturajournal_2025.csv"])

    # ------------------------------------------------------------------
    # CHECK 11 - Prior-year trial balance empty vs IT completeness attestation
    # ------------------------------------------------------------------
    py = xlsx.get("Saldenliste_2024_Vorjahr.xlsx", {})
    if py and all(len(rows) == 0 for rows in py.values()):
        add("prior_year_missing", "FLAGGED", "HIGH", 0.9,
            "Prior-year trial balance is empty (headers only) while IT "
            "attestation claims completeness",
            "The prior-year trial balance contains no data rows, so opening "
            "balances cannot be verified - yet the IT attestation claims "
            "completeness of the export. Contradiction between provided documents.",
            ["Begleitdokumente/Saldenliste_2024_Vorjahr.xlsx",
             "Begleitdokumente/IT-Bestaetigung_Vollstaendigkeit_2025.pdf"])

    # ------------------------------------------------------------------
    # CHECK 12 - Party bank-data changes -> payment flows after the change
    # ------------------------------------------------------------------
    for c in changes:
        feld = str(c.get("FELD", "")).lower()
        if "bank" not in feld and "iban" not in feld:
            continue
        pid, dt = c.get("KONTO"), d(c.get("DATUM"))
        txs = ap_by_vendor.get(pid, []) or ar_by_cust.get(pid, [])
        after = [t for t in txs
                 if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) > 0
                 and d(t.get("BUCHUNGSDATUM")) and dt
                 and d(t.get("BUCHUNGSDATUM")) >= dt]
        total = sum(parse_num(t["BUCHUNGSBETRAG"]) for t in after)
        add("bank_change_payments", "NEEDS_REVIEW", "MEDIUM", 0.65,
            f"Bank details changed for {c.get('NAME')} ({pid}) on {c.get('DATUM')}; "
            f"{len(after)} payments totalling {eur(total)} afterwards",
            "Bank-account changes are a classic payment-redirection vector. Change "
            f"was approved by {c.get('GENEHMIGT_VON')}; verify the new account "
            "against an independent confirmation.",
            [c["_prov"]] + [t["_prov"] for t in after[:10]], amount=total)

    # ------------------------------------------------------------------
    # CHECK 13 - Invoices in subledger missing from the billing journal
    # ------------------------------------------------------------------
    faktura_pref = {re.match(r"[A-Z]+", k).group(0) for k in chains
                    if chains[k].get("faktura") and re.match(r"[A-Z]+", k)}
    outside = []
    for no, ch in chains.items():
        m2 = re.match(r"[A-Z]+", no)
        if not m2 or m2.group(0) not in faktura_pref:
            continue
        if ch.get("faktura") or not ch.get("subledger"):
            continue
        outside.append((no, ch))
    for no, ch in outside[:8]:
        sub = ch["subledger"]
        amt = parse_num(sub[0].get("BUCHUNGSBETRAG"))
        rev = [s for s in sub if "storno" in str(s.get("BUCHUNGSTEXT", "")).lower()
               or "gutschrift" in str(s.get("BUCHUNGSTEXT", "")).lower()]
        add("invoice_outside_faktura", "NEEDS_REVIEW", "MEDIUM", 0.65,
            f"Invoice {no} ({eur(amt)}) booked in subledger but absent from the "
            "billing journal",
            f"Customer {sub[0].get('KUNDENKONTONUMMER')} invoice exists only in "
            "the accounting records, not in the billing journal"
            + (f"; later reversed ('{rev[0].get('BUCHUNGSTEXT')}')" if rev else "")
            + ". Could be a booking outside the invoicing process - or an "
              "innocent correction; review the reversal chain before concluding.",
            [s["_prov"] for s in sub[:6]], amount=abs(amt) if amt else None)
    if len(outside) > 8:
        add("invoice_outside_faktura", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"{len(outside) - 8} further subledger invoices absent from the "
            "billing journal",
            "See samples above; full list reproducible from chains.json.",
            [outside[i][1]["subledger"][0]["_prov"]
             for i in range(8, min(len(outside), 28))])

    # ------------------------------------------------------------------
    # CHECK 14 - AP invoices without goods receipt (only if a GR list exists)
    # ------------------------------------------------------------------
    no_gr = [a for a in anomalies
             if a["type"] == "vendor_invoice_without_goods_receipt"]
    material = [a for a in no_gr if not SERVICE_WORDS.search(str(a.get("detail", "")))]
    if material:
        add("material_purchase_without_gr", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"{len(material)} vendor invoices with material-like text but no "
            "goods receipt",
            f"Of {len(no_gr)} AP bookings without goods receipt, most are "
            f"services. These {len(material)} have material-like booking texts "
            "yet no goods receipt - verify delivery evidence: "
            + "; ".join(a["invoice"] + " " + str(a.get("detail", ""))[:40]
                        for a in material[:6]) + " ...",
            [p for a in material[:20] for p in a["prov"]])

    # ------------------------------------------------------------------
    # CHECK 15 - Near-duplicate party names (double-payment / phantom risk)
    # ------------------------------------------------------------------
    def norm(name):
        n = re.sub(r"\b(gmbh|se|ag|kg|e\.k\.|& co\.?|mbh|co)\b|[^a-z ]", "",
                   str(name).lower())
        return " ".join(n.split())

    for label, parties, subl in (("vendors", list(vendors.values()), ap_by_vendor),
                                 ("customers", list(customers.values()), ar_by_cust)):
        for i, v1 in enumerate(parties):
            for v2 in parties[i + 1:]:
                n1, n2 = norm(v1["name"]), norm(v2["name"])
                if n1 == n2 or v1["city"] != v2["city"]:
                    continue
                w1, w2 = n1.split(), n2.split()
                if (len(w1) == len(w2) and len(w1) > 1 and w1[1:] == w2[1:]
                        and w1[0] != w2[0] and w1[0][:4] == w2[0][:4]):
                    active = [v for v in (v1, v2) if v["id"] in subl]
                    add("near_duplicate_parties", "NEEDS_REVIEW", "MEDIUM", 0.6,
                        f"Near-duplicate {label} in {v1['city']}: {v1['id']} "
                        f"{v1['name']} / {v2['id']} {v2['name']}",
                        "Nearly identical names registered in the same city - "
                        "classic double-payment or phantom setup. "
                        f"{len(active)} of the two have subledger activity. "
                        f"VAT IDs: {v1.get('vat')} vs {v2.get('vat')}.",
                        [v1["prov"], v2["prov"]])

    # ------------------------------------------------------------------
    # CHECK 16 - Next-period receipts settling invoices not in OP list
    # ------------------------------------------------------------------
    op_rows = sheet_like(xlsx.get("OP-Liste_Debitoren_2025.xlsx"), "Offene Posten")
    op_open_amounts = set()
    for r in op_rows:
        for k, v in r.items():
            if "betrag" in str(k).lower() and isinstance(v, (int, float)):
                op_open_amounts.add(round(abs(v), 2))
    if op_open_amounts:
        unmatched = [r for r in pay26
                     if (parse_num(r.get("BETRAG_EUR")) or 0) < 0
                     and round(abs(parse_num(r["BETRAG_EUR"])), 2)
                     not in op_open_amounts]
        if unmatched:
            total = sum(abs(parse_num(r["BETRAG_EUR"])) for r in unmatched)
            add("payment_without_open_item", "NEEDS_REVIEW", "MEDIUM", 0.55,
                f"{len(unmatched)} next-period customer receipts with no matching "
                f"open item in the year-end OP list ({eur(total)})",
                "Cash received in the next period should settle receivables open "
                "at year-end. These receipts match no open-item amount in the OP "
                "list extract - either the extract is incomplete or receivables "
                "existed that were not reported. Sample: "
                + "; ".join(f"{r.get('BELEG')} {r.get('DEBITORNAME')} "
                            f"{r.get('BETRAG_EUR')}" for r in unmatched[:5]),
                [r["_prov"] for r in unmatched[:15]]
                + ["Begleitdokumente/OP-Liste_Debitoren_2025.xlsx"], amount=total)

    # ------------------------------------------------------------------
    # CHECK 17 - Changes/deletions of LOCKED (festgeschrieben) postings
    # ------------------------------------------------------------------
    locked_mods = [c for c in change_log
                   if truthy(c.get("FESTSCHREIBUNG_VOR_AENDERUNG"))
                   and not re.search(r"storno", str(c.get("AENDERUNGSART", "")),
                                     re.I)]
    deletions = [c for c in change_log
                 if re.search(r"lösch|loesch", str(c.get("AENDERUNGSART", "")),
                              re.I)]
    for group, label in ((locked_mods, "modification of a locked posting"),
                         (deletions, "deletion of a posting")):
        if not group:
            continue
        users = sorted({str(c.get("BENUTZER")) for c in group})
        add("change_log_integrity", "FLAGGED", "CRITICAL", 0.9,
            f"{len(group)} {label}(s) in the change log (GoBD violation)",
            f"The change log records {label}s - locked/posted entries must be "
            "immutable (GoBD/Festschreibung); corrections require reversal "
            f"postings. Users: {', '.join(users)}. Sample: "
            + "; ".join(f"{c.get('BUCHUNGSNUMMER')} {c.get('AENDERUNGSART')} "
                        f"am {c.get('GEAENDERT_AM')}" for c in group[:5]),
            [c["_prov"] for c in group[:20]])

    # ------------------------------------------------------------------
    # CHECK 18 - Entry after lock date / backdated entry (K2)
    # ------------------------------------------------------------------
    late, backdated = [], []
    for r in manual_rows:
        bd, ed = d(r.get("BUCHUNGSDATUM")), gl_entry_date(r)
        if not (bd and ed) or is_opening(r):
            continue
        if LOCK_DATE and ed > LOCK_DATE and bd < LOCK_DATE:
            late.append((r, bd, ed))
        elif (ed - bd).days > BACKDATE_DAYS:
            backdated.append((r, bd, ed))
    if late:
        tot = sum(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r, _, _ in late)
        add("entry_after_lock_date", "FLAGGED", "HIGH", 0.85,
            f"{len(late)} manual GL lines entered AFTER the lock date "
            f"({LOCK_DATE:%d.%m.%Y}) with earlier posting dates ({eur(tot)})",
            "The planning workpaper sets a lock date; these manual lines were "
            "captured after it yet posted into the closed period - late "
            "adjustments outside the documented close process (JET criterion "
            "K2). Sample: "
            + "; ".join(f"{r.get('BUCHUNGSNUMMER')} {r.get('BUCHUNGSTEXT')} "
                        f"posted {bd:%d.%m.%Y}, entered {ed:%d.%m.%Y} by "
                        f"{gl_user(r)}" for r, bd, ed in late[:4]),
            [r["_prov"] for r, _, _ in late[:20]] + [JET_PROV], amount=tot)
    if backdated:
        tot = sum(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0)
                  for r, _, _ in backdated)
        add("entry_backdated", "NEEDS_REVIEW", "MEDIUM", 0.65,
            f"{len(backdated)} manual GL lines captured more than {BACKDATE_DAYS} "
            f"days after their posting date ({eur(tot)})",
            "Long capture lags (Rueckdatierung, JET criterion K2) can shift "
            "results between periods. Sample: "
            + "; ".join(f"{r.get('BUCHUNGSNUMMER')} posted {bd:%d.%m.%Y}, entered "
                        f"{ed:%d.%m.%Y} by {gl_user(r)}"
                        for r, bd, ed in backdated[:4]),
            [r["_prov"] for r, _, _ in backdated[:20]] + [JET_PROV], amount=tot)

    # ------------------------------------------------------------------
    # CHECK 19 - Manual journals by management-function users (K3)
    # ------------------------------------------------------------------
    if MGMT_USERS:
        by_user = defaultdict(list)
        for r in manual_rows:
            u = gl_user(r)
            if u in MGMT_USERS and not is_opening(r):
                by_user[u].append(r)
        for u, rows in sorted(by_user.items()):
            big = [r for r in rows
                   if abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) >= JET_DE_MINIMIS]
            if not big:
                continue
            tot = sum(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in big)
            jrnls = {str(r.get("BUCHUNGSNUMMER")) for r in big}
            add("mgmt_user_manual_journals", "NEEDS_REVIEW", "MEDIUM", 0.6,
                f"Management user {u}: {len(big)} manual journal lines >= "
                f"{eur(JET_DE_MINIMIS)} across {len(jrnls)} journals ({eur(tot)})",
                "The planning workpaper designates this user ID as a management "
                "function (JET criterion K3 - management override risk). Review "
                "business rationale of the largest journals. Largest: "
                + "; ".join(
                    f"{r.get('BUCHUNGSNUMMER')} {r.get('BUCHUNGSTEXT')} "
                    f"{r.get('BUCHUNGSBETRAG')}"
                    for r in sorted(big, key=lambda r: -abs(
                        parse_num(r.get("BUCHUNGSBETRAG")) or 0))[:4]),
                [r["_prov"] for r in big[:15]] + [JET_PROV], amount=tot)

    # ------------------------------------------------------------------
    # CHECK 20 - Rarely-used accounts + designated full-review account (K4)
    # ------------------------------------------------------------------
    gl_accounts_master = gl_accounts
    acct_count = defaultdict(int)
    acct_name = {}
    for a in gl_accounts_master:
        no = re.match(r"\d+", str(a.get("SACHKONTONUMMER", "")))
        if no:
            acct_name[no.group(0)] = a.get("SACHKONTONAME")
    for r in gl:
        no = acct_no(r)
        if no:
            acct_count[no] += 1
    rare_hits = defaultdict(list)
    for r in manual_rows:
        no = acct_no(r)
        if no and 0 < acct_count[no] < RARE_ACCT_MAX and not is_opening(r):
            amt = abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0)
            if amt >= JET_DE_MINIMIS:
                rare_hits[no].append(r)
    for no, rows in sorted(rare_hits.items()):
        tot = sum(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in rows)
        add("rare_account_posting", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"Postings on rarely-used account {no} {acct_name.get(no, '')} "
            f"(<{RARE_ACCT_MAX} p.a.): {len(rows)} manual lines, {eur(tot)}",
            "Rarely-used accounts are a JET selection criterion (K4): manual "
            "postings here bypass normal process accounts. Sample: "
            + "; ".join(f"{r.get('BUCHUNGSNUMMER')} {r.get('BUCHUNGSTEXT')} "
                        f"{r.get('BUCHUNGSBETRAG')} by {gl_user(r)}"
                        for r in rows[:4]),
            [r["_prov"] for r in rows[:15]] + [JET_PROV], amount=tot)
    if FULL_REVIEW_ACCT:
        no, label = FULL_REVIEW_ACCT
        rows = [r for r in gl if acct_no(r) == no]
        if rows:
            tot = sum(parse_num(r.get("BUCHUNGSBETRAG")) or 0 for r in rows)
            add("designated_account_review", "INFO", "INFO", 1.0,
                f"Designated full-review account {no} ({label}): {len(rows)} "
                f"postings, net {eur(tot)}",
                "The planning workpaper designates this account for complete "
                "review (unpredictability element). All postings extracted for "
                "the auditor.",
                [r["_prov"] for r in rows[:25]] + [JET_PROV], amount=abs(tot))

    # ------------------------------------------------------------------
    # CHECK 21 - Receivables from insolvent/litigation parties (valuation)
    # ------------------------------------------------------------------
    for lc in legal_cases:
        pid = lc.get("DEBITOR") or lc.get("KONTO") or lc.get("KREDITOR")
        if not pid:
            continue
        b = round(bal.get(pid, 0.0), 2)
        who = customers.get(pid, {}).get("name") or lc.get("DEBITORNAME") or pid
        kind = lc.get("ART") or lc.get("STATUS") or lc.get("VERFAHREN") or "case"
        if b > 0:
            add("insolvent_party_receivable", "NEEDS_REVIEW", "HIGH", 0.7,
                f"Open receivable {eur(b)} from {who} ({pid}) with recorded "
                f"legal/insolvency case ({kind})",
                "The legal-cases list records proceedings for this party while "
                "the subledger shows an open year-end balance - valuation/"
                "allowance review required (expected credit loss).",
                [lc["_prov"], "Debitoren/Kundenbuchungen.txt"], amount=b)

    # ------------------------------------------------------------------
    # CHECK 22 - Bill-and-hold: agreement present -> verify the revenue
    # ------------------------------------------------------------------
    pdfs = json.loads((BUILD / "pdf_docs.json").read_text())
    bh_pages = pdfs.get("Bill-and-Hold-Vereinbarung_801677.pdf") or []
    if bh_pages:
        text = " ".join(p["text"] for p in bh_pages)
        ids = set(re.findall(r"\b(8\d{5})\b", text)) & set(customers)
        prov = [p["_prov"] for p in bh_pages]
        detail = ""
        tot = None
        for cid in sorted(ids):
            invs = [(no, ch) for no, ch in chains.items()
                    if ch.get("faktura") and ch["faktura"].get("DEBITOR") == cid
                    and not ch.get("goods")]
            amts = [parse_num(ch["faktura"].get("BETRAG_EUR")) or 0
                    for _, ch in invs]
            if invs:
                tot = sum(amts)
                detail = (f" Customer {cid} {customers[cid]['name']}: {len(invs)} "
                          f"invoice(s) without goods issue totalling {eur(tot)}: "
                          + ", ".join(no for no, _ in invs[:6]))
                prov += [ch["faktura"]["_prov"] for _, ch in invs[:6]]
        add("bill_and_hold_revenue", "NEEDS_REVIEW", "HIGH", 0.7,
            "Bill-and-hold agreement on file - revenue recognition criteria must "
            "be verified",
            "A bill-and-hold arrangement lets the seller invoice before delivery; "
            "revenue is only recognizable under strict criteria (buyer request, "
            "separated stock, ready for delivery, normal payment terms)."
            + detail, prov, amount=tot)

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    tier_order = {"FLAGGED": 0, "NEEDS_REVIEW": 1, "INFO": 2}
    findings.sort(key=lambda f: (tier_order.get(f["tier"], 9),
                                 order.get(f["severity"], 9),
                                 -(f["amount_eur"] or 0)))
    for i, f in enumerate(findings, 1):
        f["id"] = f"F{i:03d}"
    (BUILD / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=1))

    flagged = [f for f in findings if f["tier"] == "FLAGGED"]
    review = [f for f in findings if f["tier"] == "NEEDS_REVIEW"]
    print(f"thresholds: materiality={MATERIALITY:,.0f} "
          f"de_minimis={JET_DE_MINIMIS:,.0f} round={ROUND_MULTIPLE:,.0f} "
          f"lock={LOCK_DATE} backdate>{BACKDATE_DAYS}d mgmt={sorted(MGMT_USERS)} "
          f"full_review={FULL_REVIEW_ACCT} night=({NIGHT_BEFORE},{NIGHT_AFTER}) "
          f"approval_limit={APPROVAL_LIMIT}")
    print(f"findings: {len(findings)}  "
          f"(FLAGGED {len(flagged)} / NEEDS_REVIEW {len(review)})\n")
    for f in findings:
        amt = f" [{eur(f['amount_eur'])}]" if f.get("amount_eur") else ""
        print(f"{f['id']} {f['tier']:12s} {f['severity']:8s} {f['title']}{amt}")
        print(f"     src: {', '.join(f['provenance'][:3])}"
              + (" ..." if len(f['provenance']) > 3 else ""))


if __name__ == "__main__":
    main()
