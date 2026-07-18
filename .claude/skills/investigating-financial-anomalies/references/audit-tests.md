# Reusable Audit-Test Library

## Contents

- How to use this library
- Cross-cutting data checks
- Procure-to-pay and vendor integrity
- Capital expenditure and expense classification
- Period cut-off and unrecorded liabilities
- Payment authorization and threshold avoidance
- Order-to-cash and revenue
- Payroll and employee expenses
- Inventory, cash, and related parties
- Journal entries and access rights
- False-positive challenge tests
- Reusable analysis patterns

## How to use this library

Treat each section as a hypothesis family, not an expected answer. Select only tests supported by the available records. Derive thresholds, periods, account mappings, and expected controls from current-case evidence.

Use indicators to rank candidates. Do not convert an indicator directly into an allegation. Seek independent evidence of the event, mechanism, authorization, business substance, and financial effect.

## Cross-cutting data checks

Before anomaly testing:

- reconcile record counts and totals to control accounts or source reports;
- determine whether debits and credits use signs, separate columns, or transaction types;
- identify currencies, exchange-rate conventions, and tax treatment;
- distinguish event dates from entry and settlement dates;
- check duplicate keys, truncated exports, missing periods, blank identifiers, and inconsistent encodings;
- identify reversals, clearing entries, migrations, opening balances, and system-generated transactions;
- confirm whether missing records mean absence, incomplete coverage, or a process that is recorded elsewhere.

## Procure-to-pay and vendor integrity

### Vendor-master and segregation-of-duties hypotheses

- A vendor creator, approver, invoice poster, payment preparer, or payment approver has incompatible roles.
- A single user performs several critical steps for the same vendor or transaction.
- A recently created or reactivated vendor receives unusual volume relative to its peer group.
- Bank accounts, addresses, tax identifiers, phone numbers, or email domains overlap across vendors or with employees.
- Sensitive master-data changes occur shortly before invoice or payment activity.
- Approval metadata is missing, self-approved, backdated, or inconsistent with policy.

Challenge with role delegation, emergency-access logs, independent approval, migration history, shared-service arrangements, and legitimate master-data corrections.

### Business-substance hypotheses

- Invoices lack a purchase order, contract, receipt, deliverable, acceptance, or credible business owner.
- Descriptions are generic, repetitive, or inconsistent with the vendor's normal activity.
- Amounts are unusually round, recurring, or clustered, especially when other evidence is weak.
- Prices, quantities, or frequency differ materially from peers or prior periods.
- Payments occur unusually quickly, use changed bank details, or bypass normal matching.

For services, absence of a goods receipt is not decisive. Look for contracts, time records, milestones, work products, acceptance, correspondence, or other service evidence.

### Duplicate and diversion hypotheses

- The same invoice appears under altered document numbers, dates, punctuation, currencies, or vendors.
- A legitimate invoice is paid twice or paid to a changed beneficiary.
- Credit notes, reversals, or refunds do not return through the expected channel.
- Vendor statements do not reconcile to the subledger.

Confirm legal-entity boundaries, partial payments, installments, tax-only documents, prepayments, and valid recurring invoices before escalating.

## Capital expenditure and expense classification

### Hypotheses

- Routine repair, maintenance, cleaning, inspection, consumables, or recurring service is recorded as an asset.
- A capital project includes costs outside the recognition criteria or costs incurred after the asset was ready for use.
- Asset descriptions, invoice lines, project approvals, useful lives, and account classes are inconsistent.
- Several expense-like invoices are grouped into a project to meet capitalization criteria artificially.
- A genuine enhancement or component replacement is expensed despite meeting applicable recognition criteria.

### Evidence to link

Link invoice lines, purchase orders, work descriptions, investment requests, project budgets, asset cards, in-service dates, useful lives, depreciation, physical-verification records, and general-ledger postings.

Do not decide from words such as "repair," "replacement," or "overhaul" alone. Test whether the expenditure creates or improves a controlled resource, extends useful life or capacity, replaces a separately recognized component, or merely restores original condition under the applicable accounting framework.

Quantify the original classification, correct treatment, depreciation or amortization effect, tax effect when in scope, period, and balance-sheet and profit impact.

## Period cut-off and unrecorded liabilities

### Hypotheses

- Goods or services received before period end are recorded after period end without an accrual or liability.
- Revenue is recorded before transfer, acceptance, or performance.
- Posting dates are shifted while document, receipt, delivery, or service dates remain in the proper period.
- Manual reversals or post-close entries conceal a cut-off error.
- Open receipts, unmatched invoices, vendor statements, or later cash payments reveal unrecorded obligations.

### Procedure

1. Define the reporting boundary and applicable recognition rule.
2. Compare service, delivery, receipt, acceptance, invoice, posting, and payment dates.
3. Inspect transactions shortly before and after the boundary without treating the window as the only population.
4. Link post-period invoices and payments back to pre-period evidence.
5. Search accrual, liability, clearing, and reversal accounts using amount, counterparty, reference, and narrative.
6. Confirm whether an existing accrual covers the item wholly, partly, or not at all.

Distinguish a late invoice from a late-recognized obligation. Avoid double counting an invoice and its missing accrual as separate misstatements.

## Payment authorization and threshold avoidance

### Hypotheses

- Multiple payments, invoices, purchase orders, or expense claims are divided to remain below an approval threshold.
- Several near-threshold transactions share a beneficiary, date, bank account, requester, approver, payment run, contract, or underlying purpose.
- Approvals are sequenced or reassigned to bypass a higher authority.
- Aggregation rules in policy are not applied to related transactions.

### Procedure

1. Extract approval thresholds and aggregation rules from policy.
2. Group transactions at several defensible levels: beneficiary and day, beneficiary and payment run, requester and project, bank account and short time window, or shared underlying document.
3. Compare individual values with aggregate exposure.
4. Inspect invoice and payment lineage to distinguish split obligations from installments or separate deliveries.
5. Identify who initiated, approved, released, and changed each item.

Classify a confirmed bypass as a control issue unless evidence also demonstrates a financial misstatement, unauthorized payment, or loss.

## Order-to-cash and revenue

### Hypotheses

- Revenue is recorded without shipment, delivery, acceptance, or performance.
- Unusual period-end sales reverse through credit notes, returns, or cancellations after close.
- Customer identities, bank accounts, addresses, or contacts overlap unexpectedly.
- Manual price changes, rebates, discounts, side agreements, or extended payment terms alter the substance of a sale.
- Receivables age unusually, are cleared by unrelated payments, or are transferred between customers.

Challenge with contract terms, bill-and-hold criteria, valid corrections, documented rebates, customer confirmations, subsequent receipts, and ordinary seasonal patterns.

## Payroll and employee expenses

### Hypotheses

- Employees share bank accounts, addresses, tax identifiers, or contacts without a documented explanation.
- Payments continue after termination or precede authorized start dates.
- Overtime, bonuses, allowances, or expense claims cluster under approval limits or outside normal patterns.
- A user can create or amend employees and release payroll-related payments.
- Expense evidence is duplicated, altered, or inconsistent with travel and business records.

Account for legitimate joint accounts, rehiring, retroactive adjustments, expatriate arrangements, payroll corrections, and collective bonus schemes.

## Inventory, cash, and related parties

### Inventory hypotheses

- Manual quantity or valuation adjustments cluster by user, location, item, or period end.
- Negative inventory, unusual scrap, unexplained transfers, or shrinkage conflict with operational records.
- Standard costs, obsolescence reserves, or counts change without support.

### Cash hypotheses

- Bank entries do not reconcile to ledger cash or use unexplained clearing accounts.
- Payments route through unusual beneficiaries, accounts, geographies, or rapid onward transfers.
- Refunds or write-offs are directed away from the original payer or customer.

### Related-party hypotheses

- A relationship is undisclosed or transactions lack approval, support, or an economic basis.
- Pricing, terms, settlement, or classification differs from comparable transactions without explanation.

Related-party status, unusual geography, or a large loss is not inherently improper. Check disclosures, ownership records, approval, transfer-pricing support, business purpose, and subsequent settlement.

## Journal entries and access rights

### Hypotheses

- Manual entries occur at unusual times, by unusual users, or directly in rarely used accounts.
- Entries bypass subledgers, use generic narratives, lack support, or reverse immediately after close.
- Users have conflicting create, approve, post, master-data, and payment rights.
- Privileged or emergency access is used without review.
- The same credentials appear across records where independent action is expected.

Use peer and process baselines. System-generated, consolidation, allocation, recurring, and legitimate close entries can share many superficial indicators.

## False-positive challenge tests

For each high-ranked candidate, ask:

- Is there a matched clean transaction with the same superficial signal?
- Does a policy exception, approval, contract, receipt, investment case, disclosure, or operational record explain it?
- Are two similar names actually distinct legal entities?
- Does a later reversal or credit note represent a normal correction rather than concealment?
- Does a large or round transaction reflect a genuine asset, recurring allocation, rebate, financing event, or one-time settlement?
- Does an apparent low-value disposal reflect documented scrapping, destruction, or removal costs?
- Is the missing evidence expected in another system or process?
- Would the conclusion survive renamed entities, perturbed values, or a different file layout?

Document why a candidate was retained, downgraded, or dismissed.

## Reusable analysis patterns

Use business keys and invariant relationships. Adapt field names to the current schema.

### Role-conflict join

```text
master_change.entity_id = transaction.entity_id
compare creator, master_approver, poster, payment_preparer, payment_approver
flag incompatible combinations defined by current policy
```

### Cut-off bridge

```text
select operational events before reporting_boundary
link to invoices and ledger postings after reporting_boundary
exclude items covered by a valid period-end accrual
quantify uncovered recognized obligation
```

### Threshold aggregation

```text
derive threshold and aggregation rule from policy
group related items by beneficiary plus defensible time/process keys
compare individual values and aggregate exposure
inspect the underlying obligation before concluding deliberate splitting
```

### Classification consistency

```text
link invoice line -> purchase order/project -> ledger posting -> asset record
compare economic substance with recognition criteria and account treatment
compute balance-sheet and profit effects, including downstream depreciation
```

### Candidate challenge

```text
for each candidate:
  collect supporting evidence
  collect contrary evidence
  find a matched benign peer
  test alternative explanation
  retain, downgrade, or dismiss with reasons
```

