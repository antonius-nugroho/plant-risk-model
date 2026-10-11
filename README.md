# Plant Risk Model

An operational risk model for a coal-fired power plant, with a Streamlit dashboard. It turns the plant's
failure log, business (production) data, pricing, maintenance cost and coal monitoring files into:

- the **opportunity loss** of every failure event (lost energy x the price of the month it was lost),
- a **risk table and risk matrix** scored with an impact scale and a likelihood scale,
- a **Pareto of loss output** by failure mode (cause code), and
- monthly **plant KPIs** (net production, EAF, EFOR, SFC, NCF, SOF, coal reserve days, co-firing biomass).

## Quick start

### With Docker

```bash
docker compose up --build
```

Then open <http://localhost:8501>. Set `APP_PORT` to use another host port (for example
`APP_PORT=8502 docker compose up --build`). The `data/` folder and `config.yaml` are mounted read-only, so
edit the files on your machine and refresh the page.

### Without Docker

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

To run the pipeline only (writes CSVs to `data/processed`):

```bash
python main.py                   # monthly BPP
python main.py --price 900       # manual price in Rp/kWh
python main.py --basis selling_price_rp_kwh
```

## Data

The `data/` folder is **not** in the repository (it is git-ignored). Create it as follows.

```
data/
  raw/                 plant data, one file per year; any year can be added
    Business Data 2023.csv
    Failure Data 2023.csv          (.xlsx also works)
    Maintenance Cost 2023.csv
    Coal Monitoring 2023.csv
    Pricing 2023.csv               (or a single Pricing.csv with several years)
  column_description/  reference tables and column descriptions
    System Component Cause Code.csv
    Business Data Column Description.csv, Failure Data Column Desc.csv, ...
  processed/           output of main.py
```

- Files are found by name pattern (see `files:` in `config.yaml`), so a new year only needs its files dropped
  into `data/raw`. The app notices added or edited files and reloads on the next page refresh.
- All files are `;`-separated with Indonesian number formats (`1.234,56`); `-` and blanks are missing values.
- Cause codes in the failure log are matched to *System* and *Component* through
  `System Component Cause Code.csv`. A blank cause code is shown as `Unclassified`.

## How the model works

### Events

| Class | Statuses | Treatment |
|---|---|---|
| Risk | `FD.MP`, `SF`, and trips whose status is not listed elsewhere | counted as risk |
| Loss event | `FO`, `MO`, `FD`, `MD`, `PD`, `FD.SYS` | losses are measured; candidates to become risk |
| Excluded | `NC`, `RS`, `PO`, `PE`, `SHD`, `SUD` | not counted |

Move a status between the lists under `event_scope` in `config.yaml` to change this.

### Opportunity loss

`lost MWh x 1000 x price (Rp/kWh)`, priced at the month the energy was lost, per unit. Events that cross a
month boundary are split by hours. The price is BPP by default; choose the selling price or enter a manual
price in the sidebar.

### Impact scale (consequence)

An event's loss is compared with a yearly **risk limit** = `k x revenue of the previous year`
(`k` = 2%, set under `risk_limit` in `config.yaml` or in the sidebar; revenue = net energy sold x selling
price; the first year in the data uses its own revenue).

| Level | Share of the risk limit |
|---|---|
| 1 Very Low | up to 20% |
| 2 Low | over 20% up to 40% |
| 3 Moderate | over 40% up to 60% |
| 4 High | over 60% up to 80% |
| 5 Very High | over 80% |

A group's consequence is the level of its mean share per event.

### Likelihood scale (probability)

The share of months in the window in which the group had at least one event. The window is the selected
years (the latest five if more are selected).

| Level | Share of months |
|---|---|
| 1 Rare | up to 20% |
| 2 Unlikely | over 20% up to 40% |
| 3 Possible | over 40% up to 60% |
| 4 Likely | over 60% up to 80% |
| 5 Almost certain | over 80% |

### Risk score and band

`score = likelihood x consequence`: **Low** 1-4, **Medium** 5-9, **High** 10-15, **Extreme** 16-25.

### KPIs

| KPI | Definition |
|---|---|
| Net production (GWh) | net energy sold |
| Co-firing biomass (MWh) | biomass kg x kcal/kg / gross plant heat rate |
| EAF, EFOR, NCF, SOF (%) | reported values, weighted by period hours |
| SFC (kg/kWh) | coal burned / net energy sold |
| Coal reserve days | monthly average of the daily reported value (plant level) |

## Dashboard

| Tab | Content |
|---|---|
| Ranking | pick FO, MO, FD or MD: expected loss (Rp and MWh), Pareto chart and table by failure mode, risk table |
| Risk matrix | likelihood x consequence counts, with the likelihood and impact scale limits per year |
| Monthly loss | grouped bars per unit, monthly total and cumulative line, one chart per selected year |
| Events | the failure events behind the numbers |
| Data checks | data quality counts and the maintenance cost table |
| KPI | cross-year comparison, and a single-year view with each unit's contribution |

Every table has CSV and XLSX download buttons. The sidebar selects units, years, event classes, the price and
the risk limit `k`.

## Project layout

```
config.yaml            file patterns, event scope, impact and likelihood scales, price settings
main.py                command-line pipeline
streamlit_app.py       dashboard
src/risk_model/
  data_loader.py       read and clean the raw files
  classify.py          event classes
  opportunity.py       opportunity loss and price lookup
  risk.py              impact, likelihood, risk table and matrix
  kpis.py              monthly KPIs
  pipeline.py          load everything once
Dockerfile, docker-compose.yml
```

## Known data issues handled

- Failure events with `timestamp_stop` before `timestamp_start`: the end time is `start + failure_duration_hours`.
- Coal reserve readings above 40 days are treated as errors and left out of the monthly average.
- Maintenance cost is plant-level (no unit) and contains negative entries; it is shown, not allocated to events.
