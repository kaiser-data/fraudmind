# Evaluation and Anti-Overfitting Guide

## Contents

- Evaluation goals
- Leakage controls
- Test-set design
- Mutation and robustness tests
- Baseline protocol
- Scoring dimensions
- Acceptance gates
- Revision discipline

## Evaluation goals

Measure two things separately:

1. **Discovery:** the skill loads for relevant requests and stays out of unrelated work.
2. **Outcome quality:** the investigation finds supported issues, rejects false positives, cites evidence, quantifies effects, and calibrates uncertainty.

Use fresh Claude Code sessions. Authoring context, earlier answers, and previously loaded case details can conceal gaps in the skill.

## Leakage controls

- Keep gold findings, seeded-scheme definitions, expected amounts, and scoring keys outside the skill directory.
- Do not place answer keys in `CLAUDE.md`, filenames, comments, test prompts, helper scripts, or accessible working notes.
- Give the investigating session only raw case artifacts and the ordinary user request.
- Separate skill authorship, case generation, investigation, and grading contexts when practical.
- Do not revise the skill from a single missed identifier or transaction. Convert failures into general methods only when the change is defensible across cases.
- Re-run earlier hard negatives after every substantive revision.

## Test-set design

Split cases at the scenario-template or generator level, not by rows from the same generated case. Near-duplicate train and test cases overstate generalization.

Include:

- clean cases with no seeded issue;
- cases with one issue and cases with interacting issues;
- benign transactions that share superficial indicators with true issues;
- incomplete or messy exports where uncertainty is the correct result;
- different companies, charts of accounts, fiscal calendars, currencies, languages, and file organizations;
- schemes outside the initial authoring examples;
- legitimate exceptions supported by policies or documents;
- true control breaches that create no demonstrated accounting misstatement;
- true misstatements without evidence of intent.

Evaluate both realistic prevalence and deliberately difficult stress sets. Do not tune solely on a balanced set if live cases are mostly clean.

## Mutation and robustness tests

A general skill should preserve its reasoning when irrelevant surface details change. Mutate unseen cases by:

- renaming entities, users, accounts, files, sheets, and columns;
- perturbing amounts, transaction counts, and dates while preserving the underlying relationship;
- changing approval thresholds and fiscal year-ends in the policy documents;
- moving evidence across file formats or directory layouts;
- translating descriptions or using synonyms;
- inserting plausible clean transactions with similar names, round values, large values, late postings, credit notes, asset disposals, or related parties;
- adding missing records, duplicate exports, reversals, tax lines, multiple currencies, and partial payments;
- changing which source contains the decisive corroboration.

If performance collapses after a surface mutation, the skill or evaluator is probably matching literals rather than reasoning about evidence.

## Baseline protocol

For each evaluation prompt:

1. Start a fresh session with only the raw artifacts and request.
2. Run once with the skill enabled.
3. Run an equivalent fresh session with the skill disabled.
4. Grade both against the same rubric without revealing the gold answer to either run.
5. Compare correctness, false positives, evidence quality, quantification, time, and token cost.
6. Repeat nondeterministic cases enough times to distinguish a real improvement from variance.

Claude Code's official skill-creator plugin can automate isolated skill-versus-baseline comparisons, grading, and description tuning. Human review remains important for whether an allegation is fair and evidence is actually linked.

## Scoring dimensions

### Finding precision

What proportion of reported findings are supported at the claimed confidence? Penalize accusations of hard negatives more heavily than cautious leads that are clearly labeled.

### Finding recall

What proportion of material seeded or independently verified issues are found? Score partial mechanism discovery separately from full evidence linkage.

### Evidence quality

Check whether each finding:

- cites reproducible source locations and record keys;
- combines independent evidence where the conclusion requires it;
- distinguishes absence from incomplete coverage;
- records contrary evidence and alternative explanations;
- avoids relying on narrative resemblance alone.

### Classification accuracy

Check whether the output correctly separates suspected fraud, misstatement, control deficiency, compliance matter, and data-quality issue.

### Quantification accuracy

Check population, arithmetic, sign, currency, net/tax/gross basis, account, period, direction, reversals, and double counting.

### Calibration

Confidence should track evidence strength. Unsupported certainty is worse than a clearly described lead. Dismissed benign candidates should not reappear in headline conclusions.

### Robustness

Compare results across surface mutations. The mechanism and evidence path should remain stable even when names, values, paths, and wording change.

### Trigger quality

Test should-trigger and should-not-trigger prompts separately. A useful investigation skill should not load for generic coding, ordinary bookkeeping explanations, or unrelated data analysis.

## Acceptance gates

Before treating a revision as an improvement, require:

- no material increase in false accusations on clean and hard-negative cases;
- improvement across more than one scenario family or a clear fix to a general failure mode;
- accurate evidence citations and recomputed amounts;
- correct classification of control-only issues and non-intentional misstatements;
- stable results under entity, amount, date, threshold, language, and layout mutations;
- acceptable context, time, and tool cost relative to the baseline.

Prefer a smaller skill with measurable gains over a long catalogue that merely repeats domain knowledge.

## Revision discipline

When an evaluation fails:

1. Describe the abstract failure mode without copying the answer.
2. Decide whether the problem belongs in the workflow, a reusable reference, a deterministic helper, or the evaluator.
3. Make the smallest general change.
4. Test the changed scenario family, an unrelated positive family, and prior hard negatives.
5. Reject changes that improve one known case by adding literals or brittle proxies.

Examples of valid general revisions include improving date-role mapping, requiring coverage statements for negative evidence, or adding a challenge step for credit-note reversals. Invalid revisions include naming a known vendor, embedding a known threshold, or instructing the model to find a fixed count of anomalies.

