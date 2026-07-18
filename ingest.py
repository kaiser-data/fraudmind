#!/usr/bin/env python3
"""Ingest the GDPdU audit dossier, link transactions across documents, emit linked graph JSON.

Outputs (build/):
  entities.json   - customers, vendors, users, related parties (with provenance)
  chains.json     - per-invoice transaction chains linking Fakturajournal, goods lists,
                    subledger bookings, GL bookings, approval log, 2026 payments
  anomalies.json  - raw structural anomalies found while linking (input for check engine)
Every record carries provenance: source file + row number (or sheet/cell, or pdf page).
"""
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl


def _resolve_base():
    """Dossier folder: CLI arg > DOSSIER_PATH env > practice dataset default.

    Lets the same pipeline run unchanged on the final dossier:
    python3 ingest.py <path> && python3 checks.py <path>
    """
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        return Path(sys.argv[1])
    if os.environ.get("DOSSIER_PATH"):
        return Path(os.environ["DOSSIER_PATH"])
    return Path(__file__).parent / "dataset" / "Uebungsdaten Muster Verpackungen"


BASE = _resolve_base()
OUT = Path(__file__).parent / "build"
ENC = "latin-1"


def _find_file(directory, filename):
    """Resolve a dossier file tolerantly: exact name, then case-insensitive,
    then digit-stripped match (so Fakturajournal_2025.csv finds a 2026 rename).
    Raises with the folder listing so a final-dossier mismatch is fixable fast."""
    p = directory / filename
    if p.exists():
        return p
    if not directory.is_dir():
        raise FileNotFoundError(f"dossier folder missing: {directory}")
    entries = [e for e in directory.iterdir() if e.is_file()]
    by_lower = {e.name.lower(): e for e in entries}
    if filename.lower() in by_lower:
        return by_lower[filename.lower()]

    def norm(name):
        return re.sub(r"[\d_\-\s]+", "", name.lower())

    cands = [e for e in entries if norm(e.name) == norm(filename)]
    if len(cands) == 1:
        return cands[0]
    raise FileNotFoundError(
        f"{filename!r} not found in {directory} "
        f"(fuzzy candidates: {[e.name for e in cands]}; "
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


def read_csv_doc(filename):
    rows = []
    path = _find_file(BASE / "Begleitdokumente", filename)
    with open(path, encoding=ENC, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for i, row in enumerate(reader, start=2):  # row 1 = header
            row["_prov"] = f"Begleitdokumente/{path.name}:row{i}"
            rows.append(row)
    return rows


def read_xlsx_doc(filename):
    """Return {sheet_name: [row dicts]} using first plausible header row."""
    path = _find_file(BASE / "Begleitdokumente", filename)
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


def read_pdf_doc(filename):
    path = _find_file(BASE / "Begleitdokumente", filename)
    try:
        txt = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        txt = f"[pdf extraction failed: {e}]"
    pages = txt.split("\f")
    return [{"page": i + 1, "text": p.strip(),
             "_prov": f"Begleitdokumente/{path.name}:page{i + 1}"}
            for i, p in enumerate(pages) if p.strip()]


def main():
    OUT.mkdir(exist_ok=True)

    # ---------- core ledgers ----------
    customers = read_gdpdu_table("Debitoren", "Kunden.txt")
    ar = read_gdpdu_table("Debitoren", "Kundenbuchungen.txt")
    vendors = read_gdpdu_table("Kreditoren", "Lieferanten.txt")
    ap = read_gdpdu_table("Kreditoren", "Lieferantenbuchungen.txt")
    gl = read_gdpdu_table("Sachkonten", "Sachkontobuchungen.txt")

    # GL: locate ERFASSUNGSNUMMER / user by pattern (index.xml order is unreliable)
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

    # ---------- accompanying docs ----------
    faktura = read_csv_doc("Fakturajournal_2025.csv")
    wa = read_csv_doc("Warenausgangsliste_2025.csv")
    we = read_csv_doc("Wareneingangsliste_2025.csv")
    pay26 = read_csv_doc("Buchungen_Folgeperiode_2026.csv")
    changes = read_csv_doc("Stammdatenaenderungen_2025.csv")
    approvals = read_csv_doc("Freigabe-Log_Journale_2025.csv")
    shareholders = read_csv_doc("Gesellschafterliste_Beteiligungen.csv")
    creditlimits = read_csv_doc("Kreditlimitliste_Debitoren_2025.csv")

    xlsx_docs = {name: read_xlsx_doc(name) for name in [
        "OP-Liste_Debitoren_2025.xlsx", "OP-Liste_Kreditoren_2025.xlsx",
        "Saldenliste_2025.xlsx", "Saldenliste_2024_Vorjahr.xlsx",
        "Abstimmung_Nebenbuecher_HB_2025.xlsx", "Berechtigungsauswertung_2025.xlsx"]}
    pdf_docs = {name: read_pdf_doc(name) for name in [
        "JA-Entwurf_2025_Auszug_Bilanz_GuV.pdf", "IT-Bestaetigung_Vollstaendigkeit_2025.pdf",
        "Exportprotokoll_GDPdU_2025.pdf"]}

    # ---------- link transactions by invoice number ----------
    chains = defaultdict(lambda: {"faktura": None, "goods": [], "subledger": [],
                                  "gl": [], "payments_2026": [], "approval": None})
    for r in faktura:
        chains[r["RECHNUNGSNUMMER"]]["faktura"] = r
    for r in wa + we:
        chains[r["RECHNUNGSNUMMER"]]["goods"].append(r)
    for r in ar + ap:
        no = r.get("BUCHUNGSNUMMER", "")
        if re.fullmatch(r"(AR|ER)\d+", no):
            chains[no]["subledger"].append(r)

    approvals_by_no = {a["ERFASSUNGSNUMMER"]: a for a in approvals}
    for r in gl:
        doc = None
        for v in r.values():
            if isinstance(v, str) and re.fullmatch(r"(AR|ER)\d+", v):
                doc = v
                break
        if not doc:
            continue
        ch = chains[doc]
        entry = {"prov": r["_prov"], "entry_no": gl_entry_no(r), "user": gl_user(r),
                 "account": r.get("SACHKONTONUMMER"),
                 "amount": parse_num(r.get("BUCHUNGSBETRAG")),
                 "text": r.get("BUCHUNGSTEXT"), "date": r.get("BUCHUNGSDATUM")}
        ch["gl"].append(entry)
        if entry["entry_no"] and entry["entry_no"] in approvals_by_no and not ch["approval"]:
            ch["approval"] = approvals_by_no[entry["entry_no"]]

    # 2026 payments -> link to invoice by customer + exact amount
    for r in pay26:
        deb, amt_p = r.get("DEBITOR"), parse_num(r.get("BETRAG_EUR"))
        for ch in chains.values():
            f = ch["faktura"]
            if f and f.get("DEBITOR") == deb and amt_p is not None:
                amt_f = parse_num(f.get("BETRAG_EUR"))
                if amt_f is not None and abs(amt_f + amt_p) < 0.01:
                    ch["payments_2026"].append(r)

    # ---------- structural anomalies while linking ----------
    anomalies = []
    for no, ch in chains.items():
        f, goods, sub = ch["faktura"], ch["goods"], ch["subledger"]
        if no.startswith("AR"):
            if f and not goods:
                anomalies.append({"type": "invoice_without_goods_issue", "invoice": no,
                                  "prov": [f["_prov"]],
                                  "detail": f"{f.get('DEBITORNAME')} {f.get('BETRAG_EUR')} EUR {f.get('FAKTURADATUM')}"})
            if goods and not f:
                anomalies.append({"type": "goods_issue_without_invoice", "invoice": no,
                                  "prov": [g["_prov"] for g in goods]})
            if f and sub:
                a1, a2 = parse_num(f.get("BETRAG_EUR")), parse_num(sub[0].get("BUCHUNGSBETRAG"))
                # faktura is net, subledger gross: accept net, net*1.19, net*1.07
                if a1 is not None and a2 is not None and all(
                        abs(a1 * vat - a2) > 0.02 for vat in (1.0, 1.19, 1.07)):
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
                    anomalies.append({"type": "service_date_year_differs_from_invoice_year",
                                      "invoice": no, "detail": f"Leistung {ld} vs Faktura {fd}",
                                      "prov": [f["_prov"]]})
        if no.startswith("ER") and sub and not goods:
            anomalies.append({"type": "vendor_invoice_without_goods_receipt", "invoice": no,
                              "prov": [sub[0]["_prov"]],
                              "detail": sub[0].get("BUCHUNGSTEXT", "")})

    # ---------- entities ----------
    entities = {
        "company": "Muster Verpackungen GmbH",
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
    }

    (OUT / "entities.json").write_text(json.dumps(entities, ensure_ascii=False, indent=1))
    (OUT / "chains.json").write_text(json.dumps(dict(chains), ensure_ascii=False))
    (OUT / "anomalies.json").write_text(json.dumps(anomalies, ensure_ascii=False, indent=1))
    (OUT / "xlsx_docs.json").write_text(json.dumps(xlsx_docs, ensure_ascii=False, default=str))
    (OUT / "pdf_docs.json").write_text(json.dumps(pdf_docs, ensure_ascii=False))

    # ---------- report ----------
    n_full = sum(1 for c in chains.values() if c["faktura"] and c["goods"] and c["subledger"])
    print(f"customers={len(customers)} vendors={len(vendors)} gl_rows={len(gl)} "
          f"ar={len(ar)} ap={len(ap)}")
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
