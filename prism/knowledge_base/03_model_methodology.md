# Quorum Financial Model: Methodology and Definitions

The model is deterministic: the same inputs always produce the same outputs. It simulates 36 months, month by month, for each option and for a "do nothing" baseline.

## The five levers an option can use
- **Engineers:** engineers hired (0 to 20). Each costs a monthly salary and adds growth after a ramp-up period.
- **Marketing budget:** dollars spent over the marketing period. Customer acquisition cost rises as monthly spend rises.
- **Price change:** a percentage change to prices (−30% to +50%). Revenue per customer moves by that percentage; a rise loses 5% of customers up front per 10% and adds 0.2 points of monthly churn per 10%; a cut does the opposite.
- **Cost cut:** dollars per month of operating costs removed (at most 60% of operating expenses). It costs 3 months of the cut as one-off severance, and organic growth falls by 15% per 10% of operating costs cut.
- **Fundraise:** new cash added in month 1. It extends runway, and its cost of capital (15% of the amount) is counted as a cost in net value.
Any lever left at zero has no effect. An option with every lever at zero is "Keep the cash".

## Monthly simulation
For each month:
1. Revenue growth rate = organic growth − churn. After the engineer ramp-up period, add (number of new engineers × growth lift per engineer).
2. Marketing spend is the option's budget spread evenly over the marketing period (default 6 months).
3. Effective customer acquisition cost (CAC) = base CAC × (1 + monthly marketing spend ÷ the spend at which CAC doubles). Spending harder in one channel makes each customer more expensive.
4. New MRR from marketing = (monthly spend ÷ effective CAC) × average revenue per account.
5. MRR = previous MRR × (1 + growth rate) + new MRR from marketing.
6. Cash flow = MRR × gross margin − operating expenses − engineer cost − marketing spend.
7. Cash = previous cash + cash flow.

## Definitions
- **MRR:** monthly recurring revenue.
- **Runway:** months until cash falls below zero (36+ months means it never does within the horizon).
- **Runway under stress:** runway when MRR is cut by the stress shock at the start.
- **24-month net cost:** new spend (engineers, marketing, severance) plus cost of capital on money raised, minus operating-cost savings, over 24 months. A negative value means the option saves money; its payback is "immediate".
- **Added MRR at month 24:** option MRR at month 24 minus baseline MRR at month 24.
- **Net value:** extra gross profit over 24 months versus the baseline, minus the 24-month cost, plus 12 months of gross profit on the added MRR at month 24.
- **Payback:** first month in which cumulative extra gross profit covers cumulative extra cost ("beyond 24 months" if it never does in 24 months).
- **Guardrail:** minimum runway under stress an option needs to be approved.

## Default assumptions (Acme Cloud)
| Assumption | Value |
|---|---|
| Cost per engineer per month | $15K |
| Engineer ramp-up | 4 months |
| Growth lift per engineer (after ramp) | +0.4% per month |
| Base customer acquisition cost | $9K |
| Monthly spend at which CAC doubles | $150K |
| Marketing period | 6 months |
| Stress shock | −30% revenue |
| Guardrail | 15 months |

All company data in Quorum is fictional sample data for demonstration.
