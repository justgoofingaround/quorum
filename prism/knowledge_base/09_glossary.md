# Quorum Glossary

- **Quorum:** an AI board of directors that decides a company's financial question through a structured meeting of five agents.
- **Board meeting:** one run of Quorum: opening, positions, stress test, rebuttals, ruling.
- **Fact sheet:** the numbered list of figures (F1, F2, ...) produced by the financial model for a meeting. The only figures agents may quote.
- **Grounded:** an agent line whose figures all appear on the fact sheet.
- **Ungrounded figure:** a number in an agent line that is not on the fact sheet. The line is blocked when guardrails are on.
- **Guardrails on:** agents see only the fact sheet; ungrounded lines are blocked; the decision follows the board policy's rule.
- **Guardrails off:** agents improvise; used as the "before" baseline in testing.
- **Option:** one choice on the table, defined by number of engineers to hire and marketing budget.
- **Veto:** the Risk Officer's removal of an option that fails the guardrail.
- **No go:** the outcome when no option passes; the company holds its cash.
- **MRR, runway, runway under stress, net value, payback, CAC:** see the Methodology document.
