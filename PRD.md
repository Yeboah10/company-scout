# Product Requirements Document — Company Scout

**Status:** Draft v1.0
**Product:** Company Scout
**Product type:** AI-powered company intelligence and opportunity assessment tool
**Primary user:** Researcher / content strategist / business analyst
**MVP objective:** Reduce the time required to determine whether an African company is worth researching, writing about, developing into a case study, or approaching.

---

## 1. Executive Summary

Company Scout is an AI research assistant that takes a **company name or website** and produces an evidence-backed intelligence brief answering one central question:

> **"Is this company worth my time, and if so, why?"**

The product will gather information from multiple sources, distinguish facts from interpretation, identify recent developments and strategic signals, and assess the company's potential for:

- business/content stories
- academic/business case studies
- professional outreach
- deeper research

The MVP is deliberately focused on **research and opportunity assessment**.

---

## 2. Problem

Researching a company currently requires manually moving between search engines, company websites, LinkedIn, news, funding announcements, investor sites, databases, interviews, social media, PDFs and reports.

The harder problem is deciding: **Which information matters?** and **Is there enough substance here to justify spending another 2-3 hours researching this company?**

---

## 3. Product Principles (Non-negotiable)

1. **Evidence before eloquence** — prioritize factual accuracy over impressive writing
2. **Every important claim needs evidence** — no unsupported figures, dates, names, or claims
3. **Facts != interpretation** — explicitly distinguish verified fact / AI interpretation / AI hypothesis
4. **The product can say "don't bother"** — poor companies get poor scores
5. **Recency matters** — recent developments receive greater weight
6. **African context matters** — particularly good at researching African companies and markets

---

## 4. MVP Scope

### In scope
- Input: company name or website URL
- Research: company info, founders, products, geography, funding, investors, customers, recent news, expansion, hiring, strategic developments
- Analysis: important developments, strategic signals, problems/questions, story opportunities, case-study potential, outreach relevance
- Output: structured Company Intelligence Brief with source ledger
- Evidence: source, title, date, URL, confidence for each claim

### Out of scope for MVP
- Automated emails, CRM, LinkedIn automation, autonomous prospecting, content generation, lead enrichment, payments, user accounts, multi-user, mobile app, multi-agent swarm, vector database

---

## 5. Opportunity Scoring

Four scores (0-10):
- **Story Potential** (25%) — novelty, developments, market relevance, data availability
- **Case Study Potential** (25%) — strategic decision, tension, protagonist, consequences
- **Outreach Potential** (25%) — recent trigger, decision maker, value proposition
- **Research Potential** (25%) — information availability, unresolved questions, complexity

Overall Scout Score:
- 8.0-10.0: HIGH PRIORITY
- 6.0-7.9: WORTH A LOOK
- 4.0-5.9: LOW PRIORITY
- 0-3.9: SKIP

---

## 6. Source Quality Tiers

- **Tier 1:** official company, regulatory filing, government, investor, audited report, primary interview
- **Tier 2:** reputable business publication, established media, research institution
- **Tier 3:** databases, aggregators, secondary blogs (should be corroborated)

---

## 7. Success Criteria

1. Can enter a company and get a result
2. Reliably identifies the correct company
3. Researches multiple sources
4. Produces source-backed claims
5. Identifies recent developments
6. Separates facts from interpretation
7. Identifies meaningful strategic signals
8. Produces useful opportunity scores
9. Can correctly say some companies aren't worth pursuing
10. **Actually used instead of manual research**

North star metric: **Research time saved per qualified company**
