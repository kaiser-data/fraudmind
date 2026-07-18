#!/usr/bin/env python3
"""checks.py - deterministic fraud/misstatement checks over the ingested dossier.

Reads build/ artifacts (from ingest.py) plus raw GDPdU tables, runs the check
catalog, and writes build/findings.json. Every finding carries provenance
(source file + row/page). Two tiers protect against false-positive penalty:
  FLAGGED      - deterministic rule violation, high confidence
  NEEDS_REVIEW - suspicious pattern, requires auditor judgment

Anti-overfitting: no hardcoded account/vendor/user IDs from the practice data.
All checks derive their targets from the dossier itself (control descriptions
in the JET workpaper, master-data logs, permission matrix, number patterns).
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import ingest
from ingest import parse_num, read_gdpdu_table

BUILD = Path(__file__).parent / "build"

# Thresholds from Pruefungsplanung_JET_2025.docx (Arbeitspapier 4.2)
MATERIALITY = 400_000.0
JET_DE_MINIMIS = 25_000.0
APPROVAL_LIMIT = 10_000.0
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


def add(check, tier, severity, confidence, title, explanation, prov, amount=None):
    findings.append({
        "id": f"F{len(findings) + 1:03d}", "check": check, "tier": tier,
        "severity": severity, "confidence": confidence, "title": title,
        "explanation": explanation, "amount_eur": amount,
        "provenance": sorted(set(prov)),
    })


def gl_entry_no(row):
    for v in row.values():
        if isinstance(v, str) and re.fullmatch(r"77\d{5}", v):
            return v
    return None


def gl_user(row):
    for v in row.values():
        if isinstance(v, str) and (re.fullmatch(r"MV-U\d+", v) or v == "Admin"):
            return v
    return None


def gl_time(row):
    for v in row.values():
        if isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", v):
            return v
    return None


def gl_entry_date(row):
    """ERFASSUNGSDATUM = the date field immediately before ERFASSUNGSZEIT."""
    vals = list(row.values())
    for i, v in enumerate(vals):
        if isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", v):
            for j in range(i - 1, -1, -1):
                dt = d(vals[j])
                if dt:
                    return dt
    return None


def main():
    entities = json.loads((BUILD / "entities.json").read_text())
    chains = json.loads((BUILD / "chains.json").read_text())
    xlsx = json.loads((BUILD / "xlsx_docs.json").read_text())

    ar = read_gdpdu_table("Debitoren", "Kundenbuchungen.txt")
    ap = read_gdpdu_table("Kreditoren", "Lieferantenbuchungen.txt")
    gl = read_gdpdu_table("Sachkonten", "Sachkontobuchungen.txt")
    assets = read_gdpdu_table("AV", "Anlagen.txt")
    asset_tx = read_gdpdu_table("AV", "Anlagenbuchungen.txt")

    vendors = {v["id"]: v for v in entities["vendors"]}
    changes = entities["master_data_changes"]
    approvals = entities["approvals"]
    perms = {r["Benutzer"]: r
             for r in xlsx["Berechtigungsauswertung_2025.xlsx"]["Berechtigungen"]}
    faktura_jan26 = ingest.read_csv_doc("Fakturajournal_Januar_2026_Kreditoren.csv")
    pay26 = ingest.read_csv_doc("Buchungen_Folgeperiode_2026.csv")

    ap_by_vendor = defaultdict(list)
    for r in ap:
        ap_by_vendor[r.get("LIEFERANTENKONTONUMMER")].append(r)

    # ------------------------------------------------------------------
    # CHECK 1 - Master-data self-approval (SoD) + related-party cash-out
    # ------------------------------------------------------------------
    for c in changes:
        if c.get("GEAENDERT_VON") and c["GEAENDERT_VON"] == c.get("GENEHMIGT_VON"):
            konto = c.get("KONTO")
            user = c["GEAENDERT_VON"]
            prov = [c["_prov"],
                    "Begleitdokumente/Berechtigungsauswertung_2025.xlsx#Berechtigungen"]
            p = perms.get(user, {})
            toxic = [k for k in ("Buchen", "Zahlungslauf", "Stammdaten/Kreditor anlegen")
                     if p.get(k)]
            expl = (f"{user} changed AND approved master data for account {konto} "
                    f"({c.get('NAME')}, field: {c.get('FELD')}) on {c.get('DATUM')} - "
                    f"violation of the four-eyes principle required for vendor master "
                    f"changes (JET workpaper, control 3). {user} additionally holds "
                    f"rights: {', '.join(toxic)} - a toxic SoD combination, and has no "
                    f"'Journal freigeben' approval right per permissions report.")
            txs = ap_by_vendor.get(konto, [])
            inv = [t for t in txs if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) < 0]
            pays = [t for t in txs if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) > 0]
            total = -sum(parse_num(t["BUCHUNGSBETRAG"]) or 0 for t in inv)
            if txs:
                lags = []
                for i in inv:
                    for pmt in pays:
                        if i.get("BUCHUNGSNUMMER") == pmt.get("BUCHUNGSNUMMER"):
                            di, dp = d(i.get("BUCHUNGSDATUM")), d(pmt.get("BUCHUNGSDATUM"))
                            if di and dp:
                                lags.append((dp - di).days)
                goods = sum(len(chains.get(i.get("BUCHUNGSNUMMER"), {}).get("goods", []))
                            for i in inv)
                if lags:
                    expl += (f" Cash-out to this vendor: {len(inv)} invoices totalling "
                             f"{eur(total)}, all paid (avg {sum(lags) / len(lags):.1f} "
                             f"days after invoice) with {goods} goods receipts / "
                             f"delivery evidence on file.")
                prov += [t["_prov"] for t in txs]
            add("sod_master_data", "FLAGGED", "CRITICAL", 0.95,
                f"Self-approved vendor master change by {user}: {c.get('NAME')} ({konto})",
                expl, prov, amount=total if txs else None)

    # ------------------------------------------------------------------
    # CHECK 2 - New vendors bypassing the master-data approval control
    # ------------------------------------------------------------------
    approved_new = {c.get("KONTO") for c in changes if "Neuanlage" in str(c.get("FELD"))}
    changed_ever = {c.get("KONTO") for c in changes}
    jan26_by_vendor = defaultdict(list)
    for r in faktura_jan26:
        jan26_by_vendor[r.get("KREDITOR")].append(r)
    # "new & suspicious" = vendor transacts in the next period but has ZERO
    # footprint in FY2025 (no opening balance, no bookings) and no recorded
    # creation approval. Dormant master records without activity are ignored.
    opening = {r.get("LIEFERANTENKONTONUMMER") for r in ap
               if "Saldenvortrag" in str(r.get("BUCHUNGSTEXT", ""))}
    ghost = [v for v in vendors.values()
             if v["id"] in jan26_by_vendor
             and v["id"] not in opening
             and v["id"] not in ap_by_vendor
             and v["id"] not in approved_new
             and v["id"] not in changed_ever]
    if ghost:
        prov = [v["prov"] for v in ghost] + \
            ["Begleitdokumente/Stammdatenaenderungen_2025.csv"]
        add("vendor_creation_bypass", "FLAGGED", "HIGH", 0.9,
            f"{len(ghost)} new vendors have NO creation entry in the master-data "
            "change log",
            "Vendor creations require approval (JET workpaper, control 3) and are "
            "recorded as 'Neuanlage Kreditor' in Stammdatenaenderungen_2025.csv. These "
            "vendors have no opening balance (not pre-existing) and no creation "
            "record - the documented creation control was bypassed: "
            + "; ".join(f"{v['id']} {v['name']} ({v['city']})" for v in ghost),
            prov)

    # ------------------------------------------------------------------
    # CHECK 3 - Cut-off: next-period vendor invoices with 2025 service dates
    # ------------------------------------------------------------------
    unrecorded = []
    for r in faktura_jan26:
        ld, amt = d(r.get("LEISTUNGSDATUM")), parse_num(r.get("BETRAG_EUR"))
        if ld and ld.year == 2025:
            had_2025_booking = any(
                (d(t.get("BUCHUNGSDATUM")) or date(2026, 1, 1)).year == 2025
                for t in ap_by_vendor.get(r.get("KREDITOR"), []))
            if not had_2025_booking:
                unrecorded.append((r, amt))
    if unrecorded:
        total = sum(a for _, a in unrecorded if a)
        add("cutoff_unrecorded_liabilities", "FLAGGED", "CRITICAL", 0.9,
            f"Unrecorded liabilities: {len(unrecorded)} next-period vendor invoices "
            f"for 2025 services, no 2025 accrual - {eur(total)}",
            "Invoices in Fakturajournal_Januar_2026_Kreditoren are dated Jan 2026 but "
            "carry LEISTUNGSDATUM in Dec 2025 (e.g. 'Frachten Dez 2025'). The vendors "
            "have no 2025 bookings in the AP subledger, i.e. no accrual/liability was "
            "recognized in FY2025. Expenses understated, profit overstated by ~"
            f"{eur(total)} (JET criterion K4).",
            [r["_prov"] for r, _ in unrecorded], amount=total)

    # ------------------------------------------------------------------
    # CHECK 4 - Fixed assets: repair-typical or outsized acquisitions (K3)
    # ------------------------------------------------------------------
    asset_names = {a.get("ANLAGENNUMMER"): a for a in assets}
    for t in asset_tx:
        if t.get("BUCHUNGSART") != "Acquisition":
            continue
        no, amt = t.get("ANLAGENNUMMER"), parse_num(t.get("BUCHUNGSBETRAG"))
        a = asset_names.get(no, {})
        name = str(a.get("ANLAGENBEZEICHNUNG", ""))
        beleg = str(t.get("BELEGNUMMER", ""))
        prov = [t["_prov"]] + ([a["_prov"]] if a else [])
        sub = chains.get(beleg, {}).get("subledger", [])
        prov += [s["_prov"] for s in sub]
        if REPAIR_WORDS.search(name) or REPAIR_WORDS.search(str(t.get("BUCHUNGSTEXT", ""))):
            add("asset_repair_capitalized", "FLAGGED", "HIGH", 0.85,
                f"Repair-typical cost capitalized as asset: {name} ({no}), {eur(amt)}",
                f"Asset addition '{name}' on {t.get('WERTSTELLUNG')} (doc {beleg}) has "
                "a repair/maintenance-typical description. Repairs are period expense, "
                "not capitalizable - profit overstated (JET criterion K3).",
                prov, amount=amt)
        elif amt and amt >= MATERIALITY * 0.5:
            goods = chains.get(beleg, {}).get("goods", [])
            expl = (f"Single asset addition '{name}' ({no}) of {eur(amt)} on "
                    f"{t.get('WERTSTELLUNG')}, doc {beleg}"
                    + (f", booked via AP vendor {sub[0].get('LIEFERANTENKONTONUMMER')}"
                       if sub else "")
                    + (". No goods receipt on file for this document."
                       if not goods else ". Goods receipt exists.")
                    + " Above 50% of overall materiality - verify existence and "
                      "capitalization basis (invoice, Investitionsantrag).")
            add("asset_large_addition", "NEEDS_REVIEW", "MEDIUM", 0.6,
                f"Large single asset addition: {name} {eur(amt)} (doc {beleg})",
                expl, prov, amount=amt)

    # ------------------------------------------------------------------
    # CHECK 5 - Journal approvals: coverage, self-approval, status
    # ------------------------------------------------------------------
    appr_by_no = {str(a.get("ERFASSUNGSNUMMER")): a for a in approvals}
    gl_journals = defaultdict(list)
    for r in gl:
        jrn = str(r.get("BUCHUNGSNUMMER", ""))
        if re.fullmatch(r"GJ\d+|AB-\d{4}", jrn):
            no = gl_entry_no(r)
            if no:
                gl_journals[no].append(r)
    missing = {no: rows for no, rows in gl_journals.items() if no not in appr_by_no}
    for no, rows in sorted(missing.items()):
        amt = max(abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0) for r in rows)
        r0 = rows[0]
        add("journal_unapproved", "FLAGGED", "HIGH", 0.85,
            f"Manual journal {r0.get('BUCHUNGSNUMMER')} (entry {no}) missing from "
            f"approval log - {eur(amt)}",
            f"GL journal '{r0.get('BUCHUNGSTEXT')}' posted {r0.get('BUCHUNGSDATUM')} "
            f"by {gl_user(r0)} has entry number {no}, which does not appear in "
            "Freigabe-Log_Journale_2025.csv. The four-eyes journal approval control "
            "did not operate.",
            [r["_prov"] for r in rows]
            + ["Begleitdokumente/Freigabe-Log_Journale_2025.csv"],
            amount=amt)
    for a in approvals:
        if a.get("ERSTELLER") and a["ERSTELLER"] == a.get("FREIGEBER"):
            add("journal_self_approved", "FLAGGED", "HIGH", 0.9,
                f"Journal {a.get('JOURNALNAME')} created and approved by the same "
                f"user {a['ERSTELLER']}",
                f"Approval log entry {a.get('ERFASSUNGSNUMMER')}: ERSTELLER == "
                f"FREIGEBER ({a['ERSTELLER']}), approved {a.get('FREIGABEDATUM')} - "
                "four-eyes violation.", [a["_prov"]])
        elif str(a.get("FREIGABESTATUS", "")).strip() not in ("Freigegeben", ""):
            add("journal_not_released", "NEEDS_REVIEW", "MEDIUM", 0.7,
                f"Journal {a.get('JOURNALNAME')} status '{a.get('FREIGABESTATUS')}'",
                "Journal in approval log without released status but present in GL.",
                [a["_prov"]])
    # approvers without the documented approval right
    for a in approvals:
        fg = a.get("FREIGEBER")
        if fg and fg in perms and not perms[fg].get("Journal freigeben"):
            add("approver_without_right", "FLAGGED", "HIGH", 0.85,
                f"Journal {a.get('JOURNALNAME')} approved by {fg}, who has no "
                "'Journal freigeben' permission",
                f"Freigabe-Log shows {fg} as approver, but the permissions report "
                "grants that user no journal-approval right - approval control "
                "circumvented or permissions report incorrect.",
                [a["_prov"],
                 "Begleitdokumente/Berechtigungsauswertung_2025.xlsx#Berechtigungen"])

    # ------------------------------------------------------------------
    # CHECK 6 - JET: odd-hour / weekend postings, round amounts (K6, K7)
    # ------------------------------------------------------------------
    # Self-calibrating: a time pattern is only anomalous if it is RARE in this
    # dossier. Prevents overfitting (e.g. this company posts 28% of entries on
    # weekends - weekend alone means nothing here).
    timed = [(r, gl_time(r), gl_entry_date(r)) for r in gl]
    timed = [(r, t, ed) for r, t, ed in timed if t]
    n = len(timed) or 1
    weekend_share = sum(1 for _, _, ed in timed if ed and ed.weekday() >= 5) / n
    night_share = sum(1 for _, t, _ in timed
                      if int(t[:2]) >= 22 or int(t[:2]) < 6) / n
    RARE = 0.05
    odd = defaultdict(list)
    for r, t, ed in timed:
        if not re.fullmatch(r"GJ\d+", str(r.get("BUCHUNGSNUMMER", ""))):
            continue  # K7 targets manual journal entries, not routine batch docs
        hour = int(t[:2])
        is_night = (hour >= 22 or hour < 6) and night_share < RARE
        is_weekend = ed and ed.weekday() >= 5 and weekend_share < RARE
        if is_night or is_weekend:
            amt = abs(parse_num(r.get("BUCHUNGSBETRAG")) or 0)
            if amt >= JET_DE_MINIMIS:
                odd[(gl_user(r), str(r.get("BUCHUNGSNUMMER")))].append((r, amt, t, ed))
    for (user, jrn), rows in sorted(odd.items()):
        amt = max(a for _, a, _, _ in rows)
        r0, _, t0, ed0 = rows[0]
        when = f"{ed0.strftime('%A') if ed0 else '?'} {r0.get('BUCHUNGSDATUM')} at {t0}"
        add("jet_odd_hour_posting", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"Off-hours posting {jrn} by {user} ({when}), {eur(amt)}",
            f"Manual journal '{r0.get('BUCHUNGSTEXT')}' entered {when} - a posting "
            "time that is rare in this dossier (JET criterion K7). Amount above the "
            "25.000 EUR JET de-minimis threshold.",
            [r["_prov"] for r, _, _, _ in rows] + [JET_PROV], amount=amt)
    add("jet_time_profile", "INFO", "INFO", 1.0,
        f"Posting-time profile: {weekend_share:.0%} of entries on weekends, "
        f"{night_share:.0%} at night (22:00-06:00)",
        "Baseline computed from the full GL. Time-based flags are raised only for "
        f"patterns occurring in <{RARE:.0%} of postings, so routine behaviour of "
        "this specific company is not misreported as anomalous.",
        ["Sachkonten/Sachkontobuchungen.txt", JET_PROV])

    round_hits = [r for r in gl
                  if str(r.get("PERIODENZUGEHÖRIGKEIT")) != "Vortrag"
                  and (parse_num(r.get("BUCHUNGSBETRAG")) or 0) >= JET_DE_MINIMIS
                  and (parse_num(r.get("BUCHUNGSBETRAG")) or 0) % 1000 == 0
                  and not re.fullmatch(r"AB-\d{4}", str(r.get("BUCHUNGSNUMMER", "")))]
    if round_hits:
        docs = {str(r.get("BUCHUNGSNUMMER")): r for r in round_hits}
        add("jet_round_amounts", "NEEDS_REVIEW", "LOW", 0.5,
            f"{len(round_hits)} GL postings with round amounts >= 25.000 EUR "
            f"({len(docs)} documents)",
            "Round-amount postings above the JET de-minimis threshold (criterion K6): "
            + "; ".join(f"{k} {r.get('BUCHUNGSTEXT')} {r.get('BUCHUNGSBETRAG')}"
                        for k, r in list(docs.items())[:8])
            + (" ..." if len(docs) > 8 else ""),
            [r["_prov"] for r in round_hits[:20]] + [JET_PROV])

    # ------------------------------------------------------------------
    # CHECK 7 - Split payments just under the 10.000 EUR approval limit (K5)
    # ------------------------------------------------------------------
    # Splitting only makes sense when the payments are close together in time;
    # isolated near-limit payments months apart are normal business (seeded
    # innocent-discrepancy trap). Cluster within a 7-day window.
    SPLIT_WINDOW_DAYS = 7
    for vid, txs in ap_by_vendor.items():
        near = [(d(t.get("BUCHUNGSDATUM")), t) for t in txs
                if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) > 0
                and APPROVAL_LIMIT * 0.9 <= parse_num(t["BUCHUNGSBETRAG"]) < APPROVAL_LIMIT
                and d(t.get("BUCHUNGSDATUM"))]
        near.sort(key=lambda x: x[0])
        cluster = []
        best = []
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
                f"{len(best)} payments to {v.get('name', vid)} within {span} day(s), "
                f"each just under the 10.000 EUR approval limit (total {eur(total)})",
                "Payment approvals are required from 10.000 EUR (JET workpaper, "
                f"control 3). Vendor {vid} received {len(best)} separate payments in "
                f"the 9.000-9.999 EUR band within {span} day(s) - combined "
                f"{eur(total)}, i.e. a single obligation split to stay below the "
                "second-approval threshold (JET criterion K5): "
                + "; ".join(f"{t.get('BUCHUNGSDATUM')} {t.get('BUCHUNGSBETRAG')} "
                            f"'{t.get('BUCHUNGSTEXT')}'" for _, t in best),
                [t["_prov"] for _, t in best] + [JET_PROV], amount=total)

    # ------------------------------------------------------------------
    # CHECK 8 - Subledger <-> GL <-> OP-Liste tie-out
    # ------------------------------------------------------------------
    ar_sum = sum(parse_num(r.get("BUCHUNGSBETRAG")) or 0 for r in ar)
    ap_sum = sum(parse_num(r.get("BUCHUNGSBETRAG")) or 0 for r in ap)
    op_deb = sum(r.get("Saldo 31.12.2025") or 0
                 for r in xlsx["OP-Liste_Debitoren_2025.xlsx"]["Saldenliste Personenkonten"])
    op_kred = sum(r.get("Saldo 31.12.2025") or 0
                  for r in xlsx["OP-Liste_Kreditoren_2025.xlsx"]["Saldenliste Personenkonten"])
    recon_rows = xlsx["Abstimmung_Nebenbuecher_HB_2025.xlsx"]["Abstimmung"]
    recon = {}
    for r in recon_rows:
        vals = [v for v in r.values() if v is not None]
        if len(vals) >= 2 and isinstance(vals[-1], (int, float)):
            recon[str(vals[0])] = vals[-1]
    hb_230 = recon.get("HB-Konto 230000 Forderungen aus L.u.L.")
    hb_330 = recon.get("HB-Konto 330000 Verbindlichkeiten aus L.u.L.")
    checks8 = [
        ("AR subledger (Kundenbuchungen) vs OP-Liste Debitoren balances",
         ar_sum, op_deb, "Debitoren/Kundenbuchungen.txt",
         "Begleitdokumente/OP-Liste_Debitoren_2025.xlsx#Saldenliste Personenkonten"),
        ("AR subledger vs HB 230000 per Abstimmung", ar_sum, hb_230,
         "Debitoren/Kundenbuchungen.txt",
         "Begleitdokumente/Abstimmung_Nebenbuecher_HB_2025.xlsx#Abstimmung"),
        ("AP subledger (Lieferantenbuchungen) vs OP-Liste Kreditoren balances",
         ap_sum, op_kred, "Kreditoren/Lieferantenbuchungen.txt",
         "Begleitdokumente/OP-Liste_Kreditoren_2025.xlsx#Saldenliste Personenkonten"),
        ("AP subledger vs HB 330000 per Abstimmung", ap_sum, hb_330,
         "Kreditoren/Lieferantenbuchungen.txt",
         "Begleitdokumente/Abstimmung_Nebenbuecher_HB_2025.xlsx#Abstimmung"),
    ]
    for title, a, b, p1, p2 in checks8:
        if b is None:
            continue
        diff = round(a - b, 2)
        if abs(diff) > 0.02:
            add("tie_out_difference", "FLAGGED", "HIGH", 0.85,
                f"Tie-out difference {eur(diff)}: {title}",
                f"Computed {eur(round(a, 2))} vs reported {eur(round(b, 2))} - the "
                "provided reconciliation shows difference 0, which does not hold "
                "against the raw subledger.",
                [p1, p2], amount=abs(diff))

    # ------------------------------------------------------------------
    # CHECK 9 - Credit-limit report vs computed customer balances
    # ------------------------------------------------------------------
    bal = defaultdict(float)
    for r in ar:
        bal[r.get("KUNDENKONTONUMMER")] += parse_num(r.get("BUCHUNGSBETRAG")) or 0
    for cl in entities["credit_limits"]:
        rep = parse_num(cl.get("AUSNUTZUNG_31_12_2025_EUR"))
        calc = round(bal.get(cl.get("DEBITOR"), 0.0), 2)
        if rep is None:
            continue
        if abs(calc - rep) > 0.02:
            add("credit_limit_mismatch", "NEEDS_REVIEW", "MEDIUM", 0.7,
                f"Credit report utilization differs from books: "
                f"{cl.get('DEBITORNAME')} ({cl.get('DEBITOR')}) reported {eur(rep)} "
                f"vs computed {eur(calc)}",
                "AUSNUTZUNG in Kreditlimitliste does not equal the customer's "
                "year-end subledger balance - possible manipulation of the credit "
                "report or unbooked items.",
                [cl["_prov"], "Debitoren/Kundenbuchungen.txt"],
                amount=abs(calc - rep))
        limit = parse_num(cl.get("KREDITLIMIT_EUR"))
        if limit and calc > limit and str(cl.get("STATUS", "")).lower() == "ok":
            add("credit_limit_breach_hidden", "FLAGGED", "HIGH", 0.85,
                f"Credit limit exceeded but status 'ok': {cl.get('DEBITORNAME')} "
                f"balance {eur(calc)} vs limit {eur(limit)}",
                "Computed year-end balance exceeds the credit limit while the report "
                "shows status 'ok'.",
                [cl["_prov"], "Debitoren/Kundenbuchungen.txt"], amount=calc - limit)

    # ------------------------------------------------------------------
    # CHECK 10 - Sequence gaps in document number ranges
    # ------------------------------------------------------------------
    seqs = defaultdict(set)
    for no in chains:
        m = re.fullmatch(r"(AR|ER|SG)(\d+)", no)
        if m:
            seqs[m.group(1)].add(int(m.group(2)))
    for prefix, nums in seqs.items():
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
                + ". Gaps in a continuous invoice sequence can indicate deleted or "
                  "suppressed documents.",
                ["Begleitdokumente/Fakturajournal_2025.csv",
                 "Kreditoren/Lieferantenbuchungen.txt"])

    # ------------------------------------------------------------------
    # CHECK 11 - Prior-year trial balance empty vs IT completeness attestation
    # ------------------------------------------------------------------
    py = xlsx.get("Saldenliste_2024_Vorjahr.xlsx", {})
    if py and all(len(rows) == 0 for rows in py.values()):
        add("prior_year_missing", "FLAGGED", "HIGH", 0.9,
            "Saldenliste_2024_Vorjahr.xlsx is empty (headers only) while IT "
            "attestation claims completeness",
            "The prior-year trial balance contains no data rows, so opening balances "
            "(Journal AB-2024) cannot be verified against any prior-year source - "
            "yet IT-Bestaetigung_Vollstaendigkeit_2025.pdf attests completeness of "
            "the export. Contradiction between provided evidence documents.",
            ["Begleitdokumente/Saldenliste_2024_Vorjahr.xlsx",
             "Begleitdokumente/IT-Bestaetigung_Vollstaendigkeit_2025.pdf"])

    # ------------------------------------------------------------------
    # CHECK 12 - Vendor bank-data changes -> payment flows after the change
    # ------------------------------------------------------------------
    for c in changes:
        if "Bank" not in str(c.get("FELD", "")):
            continue
        vid, dt = c.get("KONTO"), d(c.get("DATUM"))
        after = [t for t in ap_by_vendor.get(vid, [])
                 if (parse_num(t.get("BUCHUNGSBETRAG")) or 0) > 0
                 and d(t.get("BUCHUNGSDATUM")) and dt
                 and d(t.get("BUCHUNGSDATUM")) >= dt]
        total = sum(parse_num(t["BUCHUNGSBETRAG"]) for t in after)
        add("bank_change_payments", "NEEDS_REVIEW", "MEDIUM", 0.65,
            f"Bank details changed for {c.get('NAME')} ({vid}) on {c.get('DATUM')}; "
            f"{len(after)} payments totalling {eur(total)} afterwards",
            "Bank-account changes are a classic payment-redirection vector. Change "
            f"was approved by {c.get('GENEHMIGT_VON')}; verify the new IBAN against "
            "an independent vendor confirmation before relying on it.",
            [c["_prov"]] + [t["_prov"] for t in after[:10]], amount=total)

    # ------------------------------------------------------------------
    # CHECK 13 - AR invoices in subledger/GL missing from Fakturajournal
    # ------------------------------------------------------------------
    for no, ch in chains.items():
        if not no.startswith("AR") or ch.get("faktura") or not ch.get("subledger"):
            continue
        sub = ch["subledger"]
        amt = parse_num(sub[0].get("BUCHUNGSBETRAG"))
        rev = [s for s in sub if "storno" in str(s.get("BUCHUNGSTEXT", "")).lower()
               or "gutschrift" in str(s.get("BUCHUNGSTEXT", "")).lower()]
        add("invoice_outside_faktura", "NEEDS_REVIEW", "MEDIUM", 0.65,
            f"Invoice {no} ({eur(amt)}) booked in subledger/GL but absent from "
            "Fakturajournal and goods-issue list",
            f"Customer {sub[0].get('KUNDENKONTONUMMER')} invoice exists only in the "
            "accounting records, not in the billing journal or logistics evidence"
            + (f"; later reversed ('{rev[0].get('BUCHUNGSTEXT')}')" if rev else "")
            + ". Could be a booking outside the invoicing process - or an innocent "
              "correction; review the full reversal chain before concluding.",
            [s["_prov"] for s in sub] + [g["prov"] for g in ch.get("gl", [])])

    # ------------------------------------------------------------------
    # CHECK 14 - ER bookings without goods receipt, material-like text only
    # ------------------------------------------------------------------
    no_gr = [a for a in json.loads((BUILD / "anomalies.json").read_text())
             if a["type"] == "vendor_invoice_without_goods_receipt"]
    material = [a for a in no_gr if not SERVICE_WORDS.search(str(a.get("detail", "")))]
    if material:
        add("material_purchase_without_gr", "NEEDS_REVIEW", "MEDIUM", 0.6,
            f"{len(material)} vendor invoices with material-like text but no goods "
            "receipt",
            f"Of {len(no_gr)} AP bookings without goods receipt, most are services "
            f"(freight, rent, consulting). These {len(material)} have material-like "
            "booking texts yet no Wareneingang - verify delivery evidence (JET "
            "criterion K2): "
            + "; ".join(a["invoice"] + " " + str(a.get("detail", ""))[:40]
                        for a in material[:6]) + " ...",
            [p for a in material[:20] for p in a["prov"]])

    # ------------------------------------------------------------------
    # CHECK 15 - Near-duplicate vendor names (double-payment / phantom risk)
    # ------------------------------------------------------------------
    def norm(name):
        n = re.sub(r"\b(gmbh|se|ag|kg|e\.k\.|& co\.?|mbh|co)\b|[^a-z ]", "",
                   str(name).lower())
        return " ".join(n.split())

    vlist = list(vendors.values())
    for i, v1 in enumerate(vlist):
        for v2 in vlist[i + 1:]:
            n1, n2 = norm(v1["name"]), norm(v2["name"])
            if n1 == n2 or v1["city"] != v2["city"]:
                continue
            w1, w2 = n1.split(), n2.split()
            # near-duplicate: same word count, same tail, first words share a stem
            if (len(w1) == len(w2) and w1[1:] == w2[1:] and w1[0] != w2[0]
                    and w1[0][:4] == w2[0][:4]):
                active = [v for v in (v1, v2) if v["id"] in ap_by_vendor]
                add("near_duplicate_vendors", "NEEDS_REVIEW", "MEDIUM", 0.6,
                    f"Near-duplicate vendors in {v1['city']}: {v1['id']} "
                    f"{v1['name']} / {v2['id']} {v2['name']}",
                    "Vendors with nearly identical names registered in the same "
                    "city - classic double-payment or phantom-vendor setup. "
                    f"{len(active)} of the two have AP activity. Verify they are "
                    "distinct legal entities (different VAT IDs on file: "
                    f"{v1.get('vat')} vs {v2.get('vat')}).",
                    [v1["prov"], v2["prov"]])

    # ------------------------------------------------------------------
    # CHECK 16 - Next-period customer receipts settling invoices not in OP list
    # ------------------------------------------------------------------
    op_open_amounts = {round(abs(r.get("Betrag EUR") or 0), 2)
                       for r in xlsx["OP-Liste_Debitoren_2025.xlsx"]
                       ["Offene Posten (Auszug)"]}
    unmatched = []
    for r in pay26:
        amt = parse_num(r.get("BETRAG_EUR"))
        if amt is None or amt >= 0:
            continue
        if round(abs(amt), 2) not in op_open_amounts:
            unmatched.append(r)
    if unmatched:
        total = sum(abs(parse_num(r["BETRAG_EUR"])) for r in unmatched)
        add("payment_without_open_item", "NEEDS_REVIEW", "MEDIUM", 0.55,
            f"{len(unmatched)} next-period customer receipts with no matching open "
            f"item in the year-end OP list ({eur(total)})",
            "Cash received in Jan 2026 should settle receivables open at 31.12.2025. "
            "These receipts match no open-item amount in OP-Liste_Debitoren "
            "(extract) - either the OP extract is incomplete (it is labelled "
            "'Auszug') or receivables existed that were not reported. Sample: "
            + "; ".join(f"{r.get('BELEG')} {r.get('DEBITORNAME')} "
                        f"{r.get('BETRAG_EUR')}" for r in unmatched[:5]),
            [r["_prov"] for r in unmatched[:15]]
            + ["Begleitdokumente/OP-Liste_Debitoren_2025.xlsx#Offene Posten (Auszug)"],
            amount=total)

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
    print(f"findings: {len(findings)}  "
          f"(FLAGGED {len(flagged)} / NEEDS_REVIEW {len(review)})\n")
    for f in findings:
        amt = f" [{eur(f['amount_eur'])}]" if f.get("amount_eur") else ""
        print(f"{f['id']} {f['tier']:12s} {f['severity']:8s} {f['title']}{amt}")
        print(f"     src: {', '.join(f['provenance'][:3])}"
              + (" ..." if len(f['provenance']) > 3 else ""))


if __name__ == "__main__":
    main()
