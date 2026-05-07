# Hansard Pipeline

This document explains how the Hansard scraping and parsing pipeline is organized and how it runs.

## 1. What this pipeline does

The pipeline takes parliamentary Hansard transcripts published online by a
legislature (currently the **Legislative Assembly of Ontario**) and turns them
into structured rows that downstream analysis can use.

There are four logical stages:

1. **Discover** — find the URLs of every Hansard "day page" we want to capture.
2. **Fetch HTML** — download each day page and store its raw HTML.
3. **Fetch PDFs** — download the PDFs linked from each day page (optional).
4. **Parse** — turn each HTML snapshot into a list of structured intervention rows (one row per speaker turn or procedural note).

All raw HTML, all PDF metadata, and all parsed rows are stored in **MongoDB** so that re-parsing never requires re-downloading.

---

## 2. Why an adapter architecture

Different jurisdictions publish Hansards in different HTML structures, but the workflow is the same: fetch, store, mark as parsed, insert rows.

So the codebase is split into:

- **Common components** (HTTP, MongoDB, logging, schema, runner) — shared by
  all jurisdictions.
- **Adapters** — one class per jurisdiction. Each adapter knows three things:
  1. how to **discover** day URLs,
  2. how to **extract PDF links** from a day page,
  3. how to **parse** a day's HTML into rows.

Adding a new jurisdiction means writing one new file in `pipeline/adapters/` and registering it. Nothing else has to change.

---

## 3. Folder structure

pipeline/
├── __init__.py
├── __main__.py              # CLI entry point: `python -m pipeline ...`
├── runner.py                # Orchestrates fetch + parse stages
├── common/
│   ├── http.py              # fetch(), retries, proxies, FetchResult
│   ├── mongo.py             # MongoDB client, collections, save helpers
│   ├── schema.py            # ROW_FIELDS list, DayPage dataclass
│   ├── text.py              # clean_text(), make_id(), helpers
│   └── logging_setup.py     # per-adapter log file setup
└── adapters/
    ├── base.py              # HansardAdapter abstract base class
    ├── registry.py          # name → adapter class lookup
    └── ontario.py           # Ontario implementation

---

## 4. How a user runs the pipeline

The pipeline is a Python package, so it runs with `python -m pipeline`.

```bash
# list available adapters
python -m pipeline --list

# run all stages (discover + fetch HTML + fetch PDFs + parse) for Ontario
python -m pipeline ontario

# only fetch (no parsing); only the most recent session's new days
python -m pipeline ontario --stage=fetch --mode=incremental

# parse whatever HTML snapshots are already in Mongo but not yet parsed
python -m pipeline ontario --stage=parse

# skip PDF downloads
python -m pipeline ontario --no-pdfs

```

### CLI flags

| Flag           | Values                          | Default     | Purpose |
|----------------|---------------------------------|-------------|---------|
| `adapter`      | name (e.g. `ontario`)           | required    | Which jurisdiction to run. |
| `--list`       | —                               | —           | Print adapters and exit. |
| `--stage`      | `all`, `fetch`, `parse`         | `all`       | Which pipeline stage(s) to run. |
| `--mode`       | `full`, `incremental`           | `full`      | Discover all sessions or only the most recent one. |
| `--batch`      | string                          | `default`   | Label stamped onto each saved snapshot for traceability. |
| `--no-pdfs`    | —                               | off         | Skip PDF downloads. |

### Environment variables

| Variable          | Default          | Purpose |
|-------------------|------------------|---------|
| `MONGO_DB_NAME`   | `case-scraping`  | Which Mongo database to read/write. |
| `PROXY_URL`       | (none)           | Optional HTTP proxy for outbound fetches. |

`build_proxies()` in `common/http.py` reads proxy settings from a `.env` file
loaded by `python-dotenv`.

---

## 5. MongoDB layout

Three collections (one DB, currently `case-scraping`):

### `hansard-html-snapshots`

One document per **(URL)** pair. Holds the raw HTML for one day.

| Field                 | Meaning |
|-----------------------|---------|
| `url`                 | Day page URL (unique). |
| `batch`               | Run label that inserted this snapshot. |
| `language`            | `"en"` or `"fr"`. |
| `jurisdiction`        | e.g. `"ontario"`. |
| `final_url`           | URL after redirects. |
| `status`              | HTTP status code. |
| `headers`             | Response headers. |
| `fetched_at`          | UTC timestamp. |
| `content`             | Raw HTML bytes. |
| `pdf_links`           | PDFs found on the page (optional). |
| `pdf_links_updated_at`| UTC timestamp. |
| `parsed`              | `True` once successfully parsed. |
| `parsed_at`           | UTC timestamp of last parse. |
| `parse_error`         | Last parse error string, or `None`. |

### `hansard-pdf-metadata`

One document per **(batch, pdf_url)**. Records the metadata of each downloaded
PDF (currently we don't store PDF bytes — just metadata).

### `hansard-parsed-rows`

One document per **intervention** (a speaker turn or a procedural note).
This is the canonical output of the pipeline. See section 6.

Indexes:
- `hansard-html-snapshots`: unique on `url` and on `(batch, url)`.
- `hansard-pdf-metadata`: unique on `(batch, pdf_url)`.
- `hansard-parsed-rows`: unique on `(source_url, ID)`.

---

## 6. The parsed row schema

Defined in `pipeline/common/schema.py` as `ROW_FIELDS`.

| Field               | Example                         | Meaning |
|---------------------|---------------------------------|---------|
| `ID`                | `2024-03-21__042`               | Stable per-row identifier (date + sequence). |
| `Date`              | `2024-03-21`                    | Sitting date (YYYY-MM-DD). |
| `jurisdiction`      | `ontario`                       | Which legislature. |
| `chamber`           | `legislative_assembly`          | Which chamber within the legislature. |
| `language`          | `en`                            | Language of the source page. |
| `OrderofBusiness`   | `STATEMENTS BY THE MINISTRY`    | High-level section heading. |
| `SubjectofBusiness` | `ONTARIO TECHNOLOGY CENTRES`    | Specific topic within the section. |
| `PersonSpeaking`    | `Hon. Mr. Walker`               | Speaker label, or `None` for procedural rows. |
| `intervention_type` | `speech` or `procedural`        | Whether this row is a speech or a procedure note. |
| `Intervention`      | `Mr. Speaker, I would like ...` | The actual text. |
| `source_url`        | `https://www.ola.org/.../hansard` | The day URL this row came from (added by the runner). |
| `upstream_license`  | (license string)                | non-commercial-use notice. |

`upstream_license` for Ontario is:

> See upstream license, including non-commercial use and other restrictions:
> https://perma.cc/D5TN-9RX6. Note: This is an unofficial reproduction of
> materials made available by the Legislative Assembly of Ontario, without
> endorsement by or affiliation with the Legislative Assembly of Ontario.

---

## 7. How parsing works (Ontario)

Ontario publishes Hansards in two distinct HTML formats across the years.

### 7a. Modern format (most parliaments)

- `<h2>` → `OrderofBusiness`.
- `<h3>` / `<h4>` → `SubjectofBusiness`.
- `<p class="speakerStart">` containing `<strong>Speaker Name:</strong> ...`
  starts a new speaker turn.
- `<p class="Procedure">` is a procedural note.
- Other `<p>` tags continue the current speaker.

### 7b. Older format (32nd, 37th, 39th parliaments observed so far)

These files don't use `<h2>`/`<h3>`. Instead they style headings as paragraphs
with a `class` attribute that mimics table cells:

- `<p class="th">` → `OrderofBusiness` (high-level section, e.g. "STATEMENT
  BY THE MINISTRY").
- `<p class="td">` → `SubjectofBusiness` (specific topic, e.g. "ONTARIO
  TECHNOLOGY CENTRES").
- Speakers are still marked by `<strong>Name:</strong>` inside a paragraph.

The parser handles both formats in one pass — it checks paragraph class names
first, falls back to `<h2>`/`<h3>` headings, and finally treats everything
else as paragraph body. The mapping is applied to every document, no matter what parliament number it comes from. the class is a sufficient signal.

### Procedural vs speech

A row is `intervention_type="procedural"` (and `PersonSpeaking=None`) when
either:
- the paragraph is `class="Procedure"`, or
- there is no current speaker and the text matches the procedural-language
  regex (`Interjections`, `Applause`, `The Speaker:`, `Pursuant to ...`, etc.).

Otherwise it's `intervention_type="speech"` with the speaker name in
`PersonSpeaking`.

---

## 8. Discovery: full vs incremental

`discover(mode)` returns the list of day URLs to fetch.

- **`full`** — walk every parliament/session listed on the root page, then
  every Hansard day URL listed on each session page. Use this when seeding a
  fresh database.
- **`incremental`** — only walk the "Recent House Documents" link on the root
  page and pull the day URLs from there. Then `runner.run_discover_and_fetch`
  filters to only URLs not already in `hansard-html-snapshots`. 

---

## 9. The runner

`pipeline/runner.py` orchestrates the stages:

- `run_discover_and_fetch(adapter, batch, mode, download_pdfs)` —
  calls `adapter.discover()`, then for each day URL fetches the HTML, calls
  `adapter.extract_pdf_links()`, saves the snapshot, and (optionally) fetches
  every PDF.
- `run_parse(adapter)` —
  finds every snapshot in this jurisdiction with `parsed != True`, calls
  `adapter.parse()`, inserts the rows into `hansard-parsed-rows`, and marks
  the snapshot as parsed (or records the parse error).
- `run_pipeline(adapter, stage, batch, mode, download_pdfs)` — the public
  entry point used by the CLI, ensures indexes exist and dispatches to the
  two functions above based on `--stage`.

Re-running a stage is safe: HTML pages are saved or updated based on URL, parsed rows are saved or updated based on (source_url, ID), and each processed HTML snapshot is marked so the parser knows what has already been handled.

---

## 10. Adding a new jurisdiction

To add e.g. Federal Hansard:

1. Create `pipeline/adapters/federal.py` with a class that subclasses
   `HansardAdapter` and sets `name`, `jurisdiction`, `chamber`,
   `supported_languages`.
2. Implement `discover(mode)`, `extract_pdf_links(html, day_url)`, and
   `parse(html, language)`.
3. Register it in `pipeline/adapters/registry.py`.
4. Run `python -m pipeline federal --mode=incremental --no-pdfs` to test.

The parsed rows will land in the same `hansard-parsed-rows` collection,
distinguishable by the `jurisdiction` field.

---

## 11. License and attribution

The pipeline fetches publicly available Hansard pages. Each parsed row carries
an `upstream_license` field with the upstream attribution / restriction
notice for that jurisdiction.
