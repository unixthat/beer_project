# CITS 3002 — Computer Networks
## Project Brief — *Battleships: Engage in Explosive Rivalry* (BEER)

---

### Introduction
Socket & Sunk has commissioned you to convert the existing single-player prototype of BEER into a fully-fledged **networked**, **turn-based** Battleship game. Your deliverable is a server that orchestrates games and a matching set of clients.

> *You may use any language (Python or C/C++ recommended).*

---

## Tiered Requirements
The project is organised into four cumulative tiers.  Each higher tier builds on—rather than replaces—earlier work.

### Tier 1 — Basic 2-Player Game (40 %)
| ID | Requirement |
|----|-------------|
| **T1.1** | Fix existing *concurrency* bug in the reference client (messages arrive out of order). |
| **T1.2** | Exactly **two** clients join; game starts automatically. |
| **T1.3** | Implement placement → turn-taking → win-detect flow. |
| **T1.4** | Simple *string/JSON* protocol is acceptable. |
| **T1.5** | No disconnection handling required. |

### Tier 2 — QoL & Scalability (15 %)
| ID | Requirement |
|----|-------------|
| **T2.1** | **Input validation** — reject malformed commands, out-of-turn shots. |
| **T2.2** | **Multiple games** in one server instance (no restart). |
| **T2.3** | **Inactivity timeout** (≈ 30 s) → forfeit / skip. |
| **T2.4** | **Detect disconnects** gracefully; server stays alive. |
| **T2.5** | **Idle/extra clients** — reject or place in a *waiting lobby*. |

### Tier 3 — Multiple Connections (15 %)
| ID | Requirement |
|----|-------------|
| **T3.1** | Accept **> 2** concurrent clients; extras become **spectators**. |
| **T3.2** | Spectators receive real-time board & event updates; their commands ignored. |
| **T3.3** | **Reconnection**: 60 s window using a client token / username. |
| **T3.4** | Automatic **next-match** selection & announcement. |

### Tier 4 — Advanced Features (20 %)
*Complete **≥ 2** tasks; **T4.1** is mandatory*

| ID  | Feature | Required Report Details |
|-----|---------|-------------------------|
| **T4.1** | **Custom low-level packet + checksum** (e.g. CRC-32). | Packet layout, checksum algorithm, error-handling policy, optional error-injection statistics. |
| **T4.2** | **Instant-messaging / chat** channel. | Command / packet design, concurrency considerations. |
| **T4.3** | **Encryption layer** (e.g. AES-CTR). | Key exchange, IV / replay, encryption placement in packet format. |
| **T4.4** | **Security flaws + mitigations**. | Vulnerability analysis, exploit demo, fix implementation & verification. |

---

## Deliverables
| # | Item | Notes |
|---|------|-------|
| 1 | **Report** (`PDF`) | ≤ 10 pages; name: `<SID1>_<SID2>_BEER.pdf` |
| 2 | **Code** (`ZIP`) | Self-contained; name: `<SID1>_<SID2>_BEER.zip` |
| 3 | **Demo video** | ≤ 10 min; public link included in report |

*Only PDF is accepted for the report.  Submit via **LMS**; one group member uploads.*

---

## Submission Checklist
- [ ] All selected tier features implemented & stable.
- [ ] README explains how to run the code on a fresh machine.
- [ ] Report & demo showcase each implemented feature.
- [ ] File names follow the SID naming convention.

---

## Rubric (summary)
| Component | NP | CR | D | **HD** |
|-----------|----|----|---|--------|
| **Tier 1 40 %** | Game unplayable | Minor concurrency issues | Fully playable | + well-documented, intuitive, best-practice code |
| **Tier 2 15 %** | < 3 feats | 3 feats | 4 feats | **all feats + high-standard design & justification** |
| **Tier 3 15 %** | < 3 feats | 3 feats | 4 feats | **all feats + advanced design** |
| **Tier 4 20 %** | Inadequate | only T4.1 | +1 task | **another task + deep networking insight** |
| **Report + Demo 10 %** | Poor | Reasonable | Clear | **Professional quality** |

> *Partial credit is possible only when earlier tiers remain stable.*
> **Start early** — focus on networking fundamentals and avoid crashes or deadlocks.
