#!/usr/bin/env python3
"""Ingest the GDPdU audit dossier, link transactions across documents, emit linked graph JSON.

Outputs (build/):
  entities.json   - customers, vendors, users, related parties (with provenance)
  chains.json     - per-invoice transaction chains linking Fakturajournal, goods lists,
                    subledger bookings, GL bookings, approval log, 2026 payments
  anomalies.json  - raw structural anomalies found while linking (input for check engine)
Every record carries provenance: source file + row number (or sheet/cell, or pdf page).

Generalization policy (audit-detectors skill): no identifiers from any specific
dossier. Document prefixes, user-ID patterns and entry-number shapes are derived
from the current dossier's own data; file names resolve fuzzily.
"""
import csv
import difflib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl


def _resolve_base():
    """Dossier folder: CLI arg > DOSSIER_PATH env > practice dataset default."""
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        return Path(sys.argv[1])
    if os.environ.get("DOSSIER_PATH"):
        return Path(os.environ["DOSSIER_PATH"])
    return Path(__file__).parent / "dataset" / "Uebungsdaten Muster Verpackungen"


BASE = _resolve_base()
OUT = Path(__file__).parent / "build"
ENC = "latin-1"

# user IDs look like XX-U05 / BSP-U02 in Dynamics exports; "Admin" = batch
USER_RE = re.compile(r"[A-Z]{2,5}-U\d+")
# document numbers: letter prefix + digits (AR1234, SI10052755, PI037335, ...)
DOC_RE = re.compile(r"[A-Z]{2,6}\d{4,}")


def _find_file(directory, filename, optional=False):
    """Resolve a dossier file tolerantly: exact, case-insensitive, then best
    difflib match on the lowercase stem (unique winner >= 0.6 similarity).
    Loud error listing the folder contents so a mismatch is fixable fast."""
    p = directory / filename
    if p.exists():
        return p
    if not directory.is_dir():
        if optional:
            return None
        raise FileNotFoundError(f"dossier folder missing: {directory}")
    entries = [e for e in directory.iterdir() if e.is_file()]
    by_lower = {e.name.lower(): e for e in entries}
    if filename.lower() in by_lower:
        return by_lower[filename.lower()]
    want = filename.lower().rsplit(".", 1)[0]
    ext = filename.lower().rsplit(".", 1)[-1]
    pool = [e for e in entries if e.name.lower().endswith(ext)]
    # period/date tokens must carry over (Fakturajournal_2025 must not
    # resolve to Fakturajournal_Januar_2026)
    digits = re.findall(r"\d+", want)
    with_digits = [e for e in pool
                   if all(g in e.name.lower() for g in digits)]
    if digits and with_digits:
        pool = with_digits
    scored = sorted(
        ((difflib.SequenceMatcher(
            None, want, e.name.lower().rsplit(".", 1)[0]).ratio(), e)
         for e in pool),
        key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.6 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] > 0.05):
        return scored[0][1]
    if optional:
        return None
    raise FileNotFoundError(
        f"{filename!r} not found in {directory} "
        f"(best fuzzy: {[(round(s, 2), e.name) for s, e in scored[:3]]}; "
        f"available: {sorted(e.name for e in entries)})")


def parse_num(s):
    """German number '46044,67' or '-6374,83' -> float. Empty -> None."""
    if s is None or str(s).strip() == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def read_gdpdu_table(module, filename):
    """Read a GDPdU txt table; returns list of dicts with _prov. Columns from index.xml."""
    path = _find_file(BASE / module, filename)
    idx = _find_file(BASE / module, "index.xml").read_text(encoding="utf-8", errors="replace")
    tables = re.findall(r"<Table>(.*?)</Table>", idx, re.S)
    cols = None
    for t in tables:
        url = re.search(r"<URL>([^<]+)</URL>", t)
        if url and url.group(1) in (filename, path.name):
            cols = re.findall(r"<Name>([^<]+)</Name>", t)[1:]  # first <Name> is table name
    rows = []
    with open(path, encoding=ENC, newline="") as f:
        for i, rec in enumerate(csv.reader(f, delimiter=";", quotechar='"'), start=1):
            if not rec:
                continue
            if cols and len(rec) == len(cols):
                row = dict(zip(cols, rec))
            else:
                row = {f"C{j}": v for j, v in enumerate(rec)}
            row["_prov"] = f"{module}/{path.name}:row{i}"
            rows.append(row)
    return rows


def read_csv_doc(filename, optional=False):
    rows = []
    path = _find_file(BASE / "Begleitdokumente", filename, optional=optional)
    if path is None:
        return rows
    with open(path, encoding=ENC, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for i, row in enumerate(reader, start=2):  # row 1 = header
            row["_prov"] = f"Begleitdokumente/{path.name}:row{i}"
            rows.append(row)
    return rows


def read_xlsx_doc(filename, optional=False):
    """Return {sheet_name: [row dicts]} using first plausible header row."""
    path = _find_file(BASE / "Begleitdokumente", filename, optional=optional)
    if path is None:
        return {}
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = {}
    for ws in wb.worksheets:
        data = list(ws.values)
        if not data:
            continue
        h = 0
        while h < len(data) and sum(v is not None for v in data[h]) < 2:
            h += 1
        if h >= len(data):
            continue
        header = [str(c) if c is not None else f"col{j}" for j, c in enumerate(data[h])]
        rows = []
        for i, rec in enumerate(data[h + 1:], start=h + 2):
            row = dict(zip(header, rec))
            row["_prov"] = f"Begleitdokumente/{path.name}#{ws.title}:row{i}"
            rows.append(row)
        sheets[ws.title] = rows
    return sheets


def read_pdf_doc(filename, optional=False):
    path = _find_file(BASE / "Begleitdokumente", filename, optional=optional)
    if path is None:
        return []
    try:
        txt = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        txt = f"[pdf extraction failed: {e}]"
    pages = txt.split("\f")
    return [{"page": i + 1, "text": p.strip(),
             "_prov": f"Begleitdokumente/{path.name}:page{i + 1}"}
            for i, p in enumerate(pages) if p.strip()]


def read_docx_text(filename, optional=True):
    """Plain text of a .docx (stdlib zipfile; no python-docx dependency)."""
    path = _find_file(BASE / "Begleitdokumente", filename, optional=optional)
    if path is None:
        return ""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def gl_user(row):
    """Posting user: pattern-derived (XX-Unn) or batch 'Admin'."""
    u = row.get("BENUTZERKENNUNG")
    if isinstance(u, str) and (USER_RE.fullmatch(u) or u == "Admin"):
        return u
    for v in row.values():
        if isinstance(v, str) and (USER_RE.fullmatch(v) or v == "Admin"):
            return v
    return None


def gl_entry_no(row, valid_prefixes=None):
    """Journal entry number: last standalone 7-12 digit token in the row
    (entry fields sit at the end of GDPdU journal rows). If a set of known
    prefixes from the approval log is given, prefer a token matching it."""
    cands = [v for v in row.values()
             if isinstance(v, str) and re.fullmatch(r"\d{7,12}", v)]
    if not cands:
        return None
    if valid_prefixes:
        pref = [c for c in cands if c[:4] in valid_prefixes]
        if pref:
            return pref[-1]
    return cands[-1]


def main():
    OUT.mkdir(exist_ok=True)

    # ---------- core ledgers ----------
    customers = read_gdpdu_table("Debitoren", "Kunden.txt")
    ar = read_gdpdu_table("Debitoren", "Kundenbuchungen.txt")
    vendors = read_gdpdu_table("Kreditoren", "Lieferanten.txt")
    ap = read_gdpdu_table("Kreditoren", "Lieferantenbuchungen.txt")
    gl = read_gdpdu_table("Sachkonten", "Sachkontobuchungen.txt")

    # company name = first <Name> in the GL index.xml
    company = "?"
    idx_path = _find_file(BASE / "Sachkonten", "index.xml", optional=True)
    if idx_path:
        m = re.search(r"<Name>([^<]+)</Name>", idx_path.read_text(
            encoding="utf-8", errors="replace"))
        if m:
            company = m.group(1)

    # ---------- accompanying docs (all fuzzy-resolved; missing -> empty) ----------
    faktura = read_csv_doc("Fakturajournal_2025.csv")
    wa = read_csv_doc("Warenausgangsliste_2025.csv", optional=True)
    we = read_csv_doc("Wareneingangsliste_2025.csv", optional=True)
    # fuzzy resolution may map two requested names onto ONE existing file
    # (Wareneingang vs Warenausgang); a duplicate resolution means the second
    # document does not exist in this dossier
    if we and wa and we[0]["_prov"] == wa[0]["_prov"]:
        we = []
    pay26 = read_csv_doc("Buchungen_Folgeperiode_2026.csv", optional=True)
    changes = read_csv_doc("Stammdatenaenderungen_2025.csv", optional=True)
    approvals = read_csv_doc("Freigabe-Log_Journale_2025.csv", optional=True)
    shareholders = read_csv_doc("Gesellschafterliste_Beteiligungen.csv", optional=True)
    creditlimits = read_csv_doc("Kreditlimitliste_Debitoren_2025.csv", optional=True)
    changelog = read_csv_doc("Aenderungsprotokoll_2025.csv", optional=True)
    statuslist = read_csv_doc("Stammdaten-Statusliste_2025.csv", optional=True)
    legalcases = read_csv_doc("Rechtsfaelle_Insolvenzen.csv", optional=True)
    acctmap = read_csv_doc("Kontenplan-Mapping.csv", optional=True)

    # normalize the master-data change log across dossier variants:
    # KONTO <- DEBITOR/KREDITOR/KONTO, NAME <- *NAME
    for c in changes:
        if not c.get("KONTO"):
            c["KONTO"] = c.get("DEBITOR") or c.get("KREDITOR") or c.get("KONTONUMMER")
        if not c.get("NAME"):
            c["NAME"] = (c.get("DEBITORNAME") or c.get("KREDITORNAME")
                         or c.get("LIEFERANTENNAME"))

    xlsx_docs = {name: read_xlsx_doc(name, optional=True) for name in [
        "OP-Liste_Debitoren_2025.xlsx", "OP-Liste_Kreditoren_2025.xlsx",
        "Saldenliste_2025.xlsx", "Saldenliste_2024_Vorjahr.xlsx",
        "Abstimmung_Nebenbuecher_HB_2025.xlsx", "Berechtigungsauswertung_2025.xlsx"]}
    pdf_docs = {name: read_pdf_doc(name, optional=True) for name in [
        "JA-Entwurf_2025_Auszug_Bilanz_GuV.pdf", "IT-Bestaetigung_Vollstaendigkeit_2025.pdf",
        "Exportprotokoll_GDPdU_2025.pdf", "Bill-and-Hold-Vereinbarung_801677.pdf"]}
    planning_text = read_docx_text("Pruefungsplanung_JET_2025.docx")

    # ---------- derive document-number prefixes from THIS dossier ----------
    def doc_prefix(no):
        m = DOC_RE.fullmatch(str(no or ""))
        return re.match(r"[A-Z]+", m.group(0)).group(0) if m else None

    prefix_count = Counter()
    for r in faktura:
        p = doc_prefix(r.get("RECHNUNGSNUMMER"))
        if p:
            prefix_count[p] += 1
    for r in ar + ap:
        p = doc_prefix(r.get("BUCHUNGSNUMMER"))
        if p:
            prefix_count[p] += 1
    for r in wa + we:
        p = doc_prefix(r.get("RECHNUNGSNUMMER"))
        if p:
            prefix_count[p] += 1
    doc_prefixes = {p for p, n in prefix_count.items() if n >= 3}

    def is_doc_no(v):
        return (isinstance(v, str) and DOC_RE.fullmatch(v)
                and re.match(r"[A-Z]+", v).group(0) in doc_prefixes)

    # AR-side vs AP-side prefixes (which subledger uses them as invoice numbers)
    ar_prefixes = {doc_prefix(r.get("BUCHUNGSNUMMER")) for r in ar} - {None}
    ap_prefixes = {doc_prefix(r.get("BUCHUNGSNUMMER")) for r in ap} - {None}
    ar_prefixes |= {doc_prefix(r.get("RECHNUNGSNUMMER")) for r in faktura} - {None}

    # ---------- link transactions by invoice number ----------
    chains = defaultdict(lambda: {"faktura": None, "goods": [], "subledger": [],
                                  "gl": [], "payments_2026": [], "approval": None})
    for r in faktura:
        no = r.get("RECHNUNGSNUMMER")
        if no:
            chains[no]["faktura"] = r
    for r in wa + we:
        no = r.get("RECHNUNGSNUMMER")
        if no:
            chains[no]["goods"].append(r)
    for r in ar + ap:
        no = r.get("BUCHUNGSNUMMER", "")
        if is_doc_no(no):
            chains[no]["subledger"].append(r)

    appr_prefixes = {str(a.get("ERFASSUNGSNUMMER", ""))[:4]
                     for a in approvals if a.get("ERFASSUNGSNUMMER")}
    approvals_by_no = {str(a["ERFASSUNGSNUMMER"]): a for a in approvals
                       if a.get("ERFASSUNGSNUMMER")}
    for r in gl:
        doc = None
        for key in ("DOKUMENT", "BELEGNUMMER", "BUCHUNGSNUMMER"):
            v = r.get(key)
            if is_doc_no(v):
                doc = v
                break
        if not doc:
            for v in r.values():
                if is_doc_no(v):
                    doc = v
                    break
        if not doc:
            continue
        ch = chains[doc]
        entry = {"prov": r["_prov"], "entry_no": gl_entry_no(r, appr_prefixes),
                 "user": gl_user(r),
                 "account": r.get("SACHKONTONUMMER"),
                 "amount": parse_num(r.get("BUCHUNGSBETRAG")),
                 "text": r.get("BUCHUNGSTEXT"), "date": r.get("BUCHUNGSDATUM")}
        ch["gl"].append(entry)
        if entry["entry_no"] and entry["entry_no"] in approvals_by_no and not ch["approval"]:
            ch["approval"] = approvals_by_no[entry["entry_no"]]

    # 2026 payments -> link to invoice by customer + exact amount
    pay26_by_deb = defaultdict(list)
    for r in pay26:
        amt = parse_num(r.get("BETRAG_EUR"))
        if amt is not None:
            pay26_by_deb[r.get("DEBITOR")].append((amt, r))
    for ch in chains.values():
        f = ch["faktura"]
        if not f:
            continue
        amt_f = parse_num(f.get("BETRAG_EUR"))
        if amt_f is None:
            continue
        for amt_p, r in pay26_by_deb.get(f.get("DEBITOR"), []):
            if abs(amt_f + amt_p) < 0.01:
                ch["payments_2026"].append(r)

    # ---------- structural anomalies while linking ----------
    anomalies = []
    have_wa, have_we = bool(wa), bool(we)
    for no, ch in chains.items():
        f, goods, sub = ch["faktura"], ch["goods"], ch["subledger"]
        pref = doc_prefix(no)
        is_ar = pref in ar_prefixes
        is_ap = pref in ap_prefixes and not is_ar
        if is_ar:
            if f and not goods and have_wa:
                art = str(f.get("ART", ""))
                if "gutschrift" not in art.lower():
                    anomalies.append(
                        {"type": "invoice_without_goods_issue", "invoice": no,
                         "prov": [f["_prov"]],
                         "detail": f"{f.get('DEBITORNAME')} {f.get('BETRAG_EUR')} EUR "
                                   f"{f.get('FAKTURADATUM')}"})
            if goods and not f:
                anomalies.append({"type": "goods_issue_without_invoice", "invoice": no,
                                  "prov": [g["_prov"] for g in goods]})
            if f and sub:
                a1 = parse_num(f.get("BETRAG_EUR"))
                a2 = parse_num(sub[0].get("BUCHUNGSBETRAG"))
                # faktura may be net, subledger gross: accept net, net*1.19, net*1.07
                if a1 is not None and a2 is not None and all(
                        abs(a1 * vat - abs(a2)) > 0.02 and abs(a1 * vat + a2) > 0.02
                        for vat in (1.0, 1.19, 1.07)):
                    anomalies.append({"type": "amount_mismatch_faktura_vs_subledger",
                                      "invoice": no, "faktura_net": a1, "subledger": a2,
                                      "prov": [f["_prov"], sub[0]["_prov"]]})
            if f and goods:
                a1 = parse_num(f.get("BETRAG_EUR"))
                a3 = sum(parse_num(g.get("BETRAG_EUR")) or 0 for g in goods)
                if a1 is not None and abs(a1 - a3) > 0.01:
                    anomalies.append({"type": "amount_mismatch_faktura_vs_goods",
                                      "invoice": no, "diff": round(a1 - a3, 2),
                                      "prov": [f["_prov"]] + [g["_prov"] for g in goods]})
            if f and f.get("LEISTUNGSDATUM") and f.get("FAKTURADATUM"):
                ld, fd = f["LEISTUNGSDATUM"], f["FAKTURADATUM"]
                if ld[-4:] != fd[-4:]:
                    anomalies.append(
                        {"type": "service_date_year_differs_from_invoice_year",
                         "invoice": no, "detail": f"Leistung {ld} vs Faktura {fd}",
                         "prov": [f["_prov"]]})
        if is_ap and sub and not goods and have_we:
            anomalies.append({"type": "vendor_invoice_without_goods_receipt", "invoice": no,
                              "prov": [sub[0]["_prov"]],
                              "detail": sub[0].get("BUCHUNGSTEXT", "")})

    # ---------- entities ----------
    entities = {
        "company": company,
        "customers": [{"id": c.get("KUNDENKONTONUMMER"), "name": c.get("KUNDENNAME"),
                       "vat": c.get("KUNDENUSTIDNR"), "city": c.get("KUNDENORT"),
                       "prov": c["_prov"]} for c in customers],
        "vendors": [{"id": v.get("LIEFERANTENKONTONUMMER"), "name": v.get("LIEFERANTENNAME"),
                     "vat": v.get("LIEFERANTENUSTIDNR"), "city": v.get("LIEFERANTENORT"),
                     "prov": v["_prov"]} for v in vendors],
        "users": sorted({u for u in (gl_user(r) for r in gl) if u}),
        "shareholders": shareholders,
        "master_data_changes": changes,
        "approvals": approvals,
        "credit_limits": creditlimits,
        "change_log": changelog,
        "status_list": statuslist,
        "legal_cases": legalcases,
        "account_map": acctmap,
        "doc_prefixes": {"ar": sorted(p for p in ar_prefixes if p),
                         "ap": sorted(p for p in ap_prefixes if p)},
    }

    (OUT / "entities.json").write_text(json.dumps(entities, ensure_ascii=False, indent=1))
    (OUT / "chains.json").write_text(json.dumps(dict(chains), ensure_ascii=False))
    (OUT / "anomalies.json").write_text(json.dumps(anomalies, ensure_ascii=False, indent=1))
    (OUT / "xlsx_docs.json").write_text(json.dumps(xlsx_docs, ensure_ascii=False, default=str))
    (OUT / "pdf_docs.json").write_text(json.dumps(pdf_docs, ensure_ascii=False))
    (OUT / "planning_text.txt").write_text(planning_text)

    # ---------- report ----------
    n_full = sum(1 for c in chains.values() if c["faktura"] and c["goods"] and c["subledger"])
    print(f"company={company}")
    print(f"customers={len(customers)} vendors={len(vendors)} gl_rows={len(gl)} "
          f"ar={len(ar)} ap={len(ap)}")
    print(f"doc_prefixes={sorted(doc_prefixes)} ar={sorted(p for p in ar_prefixes if p)} "
          f"ap={sorted(p for p in ap_prefixes if p)}")
    print(f"chains={len(chains)} fully_linked={n_full} "
          f"gl_linked={sum(1 for c in chains.values() if c['gl'])} "
          f"approved={sum(1 for c in chains.values() if c['approval'])} "
          f"paid_2026={sum(1 for c in chains.values() if c['payments_2026'])}")
    by_type = defaultdict(int)
    for a in anomalies:
        by_type[a["type"]] += 1
    print(f"anomalies={len(anomalies)}")
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
