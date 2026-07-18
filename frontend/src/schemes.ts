export interface SchemeInfo {
  label: string
  kind: string
  meaning: string
}

// Maps engine check identifiers (stable across dossiers) to auditor-facing
// scheme context: what pattern this is and why it matters. Falls back to a
// prettified check name for checks added later.
const SCHEMES: Record<string, SchemeInfo> = {
  sod_master_data: {
    label: 'Master-data self-approval (SoD override)',
    kind: 'Control override · vendor-fraud pattern',
    meaning: 'The same user changed and approved vendor master data, and '
      + 'payments followed. This is the typical setup for fictitious-vendor '
      + 'or related-party schemes.',
  },
  cutoff_unrecorded_liabilities: {
    label: 'Period cut-off — unrecorded liabilities',
    kind: 'Financial misstatement',
    meaning: 'Expenses for services received this year were first recorded '
      + 'in the next period, understating liabilities and overstating profit.',
  },
  asset_repair_capitalized: {
    label: 'Improper capitalization of repairs',
    kind: 'Financial misstatement',
    meaning: 'Repair or maintenance cost was booked as a fixed asset. That '
      + 'spreads the expense over years and overstates current profit.',
  },
  split_payments_under_limit: {
    label: 'Payment splitting below approval limit',
    kind: 'Control circumvention',
    meaning: 'Several payments, each just under the approval threshold, made '
      + 'close together in time — the pattern used to bypass the four-eyes '
      + 'payment control.',
  },
  vendor_creation_bypass: {
    label: 'Vendors created outside the change log',
    kind: 'Control deficiency · ghost-vendor risk',
    meaning: 'New vendors transact but have no creation entry in the '
      + 'master-data change log — the audit trail for who created them is '
      + 'missing.',
  },
  prior_year_missing: {
    label: 'Evidence contradiction (completeness)',
    kind: 'Data integrity',
    meaning: 'A delivered file is empty although the IT attestation certifies '
      + 'completeness — the provided evidence contradicts itself.',
  },
  asset_large_addition: {
    label: 'Unusually large asset addition',
    kind: 'Needs verification',
    meaning: 'A single large addition to fixed assets. Legitimate investment '
      + 'is common — verify invoice, board approval and physical existence.',
  },
  bank_change_payments: {
    label: 'Bank details changed before payments',
    kind: 'Payment-diversion risk',
    meaning: 'Vendor bank data changed shortly before sizable payments — the '
      + 'pattern seen in payment-diversion fraud, but also normal after a '
      + 'genuine bank switch.',
  },
  sequence_gap: {
    label: 'Gaps in document number sequence',
    kind: 'Completeness risk',
    meaning: 'Missing document numbers can mean deleted or suppressed '
      + 'records — or simply voided documents. Completeness must be verified.',
  },
  invoice_outside_faktura: {
    label: 'Booking outside the invoicing pipeline',
    kind: 'Revenue integrity',
    meaning: 'A revenue booking exists in the ledgers but not in the invoice '
      + 'journal or goods-issue list — possible manual or fictitious entry.',
  },
  material_purchase_without_gr: {
    label: 'Purchases without goods receipt',
    kind: 'Three-way-match gap',
    meaning: 'Material-like vendor invoices without a recorded goods receipt '
      + 'weaken the match between order, delivery and invoice.',
  },
  near_duplicate_vendors: {
    label: 'Near-duplicate vendor records',
    kind: 'Master-data quality · duplicate-payment risk',
    meaning: 'Two vendors with nearly identical names in the same city — '
      + 'duplicate payments or a look-alike ghost vendor are possible.',
  },
  jet_time_profile: {
    label: 'Posting-time baseline',
    kind: 'Calibration information',
    meaning: 'The base rate of weekend/night postings in this dataset — '
      + 'context for judging time-based anomalies, not itself an exception.',
  },
}

export function schemeFor(check: string): SchemeInfo {
  return SCHEMES[check] ?? {
    label: check.replace(/_/g, ' '),
    kind: 'Engine check',
    meaning: 'Deterministic rule result — open the engine finding below for '
      + 'the exact logic and evidence.',
  }
}
