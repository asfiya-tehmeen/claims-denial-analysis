I'm a Dubai-based analyst job seeker. My **top target is medical insurance**: insurers, TPAs (third-party administrators) and hospital revenue-cycle teams in the UAE (Daman, Dubai Insurance, AXA/GIG, Cigna, NAS, Nextcare, MedNet, Mediclinic, Aster, SEHA/M42). Their analyst job descriptions ask for SQL, Power BI, Excel, claims and policy data, and denial management. This is my most important remaining project. It hasn't started. `README.md` is a 7 to 9 day plan, and the original lighter plan is in `README_v1_original.md`.

I'm job hunting full-time, so **first rewrite the plan into a 6-day core version** and show me the diff before writing code.

## Keep (this is the pitch)
- The data-honesty line at the top of every output: claims are simulated using the published DHA eClaimLink field structure (with a NPHIES mapping note in the data dictionary). Code sets, edit rules and benchmarks come from real public sources. Verify each source before relying on it, and mark anything unverified.
- **Scope cut:** about 50K claims / ~150K activity lines, 18 to 24 months, 1 hospital group, 6 payers (fictional names), 6 to 8 service lines. Simulate at the **line (activity) level**, with partial payments and remittance advice.
- Denial categories following the eClaimLink denial-code groups (eligibility, authorisation, coding, medical necessity, non-covered, duplicate, timely filing, price).
- Planted effects with a hidden answer key, including one payer that changes its authorisation behaviour mid-period. Analysis code must not read the key until a final scoring step. Because the generator knows each line's true denial probability, report the best achievable AUC and Brier score next to the model's.
- **SQL is the core, not an extra:** build the RCM (revenue-cycle) KPI layer in DuckDB SQL (`sql/`): clean claim rate, first-pass yield, denial rate by count and by value, avoidable-denial share, A/R days, resubmission overturn rate, and a payer scorecard. Check payment-timeline rules against the actual published Dubai claims-management directive before encoding them.
- **Rules vs ML:** a rule-based scrubber (using real CMS NCCI / MUE edits where they apply to CPT codes) vs logistic regression vs LightGBM, plus calibration curves and SHAP drivers. **The headline metric is AED recovered per coder hour** under a fixed review capacity, alongside AUC.
- A payer-behaviour change detector for the planted mid-period change: how many weeks it took to detect, and how many false alarms it raised.
- `REPORT.md` written as a memo to an RCM director: where revenue leaks, what to review first, and which payer changed.

## Power BI is now core (move it out of stretch)
Export a star schema (`fact_claim_line`, `fact_remittance`, `dim_payer`, `dim_service_line`, `dim_provider`, `dim_date`, `dim_denial_code`) to `reports/powerbi/`, plus `MEASURES.md` with the DAX for every KPI above and a layout spec for 2 pages (RCM overview; payer scorecard). Gulf hospital and insurer teams use Power BI. I'll build the .pbix myself, so make the spec precise enough to follow step by step.

## Drop or park (list them under "Future work")
- Decoy patterns and the Simpson's-paradox trap (keep one paragraph on why a mix-adjusted denial rate matters)
- Kaplan-Meier / Cox time-to-payment models (use median days-to-payment by payer in SQL instead)
- The Streamlit app, the monthly pack generator, FHIR export, the LLM remittance-comment classifier, and CI

## Rules
- Seeded generator with tests, so the whole pipeline reproduces.
- Never report a number you haven't run. If ML adds little over the rules, that's a valid finding. Report it honestly in AED terms.
- Don't claim anything about real Gulf denial rates.
- At the end, run the tests, show the results, and give me 3 resume bullets that use only measured numbers: one SQL/KPI, one ML in AED terms, one Power BI.
