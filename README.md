# Ontario Hansard Scraper and Parser

This project downloads Ontario Hansard HTML pages and parses them into structured transcript rows stored in MongoDB.

## Overview

The pipeline:
1. discovers Hansard session/day pages
2. downloads raw HTML snapshots
3. stores raw HTML in MongoDB
4. parses HTML into structured transcript rows
5. stores parsed rows in MongoDB

## MongoDB collections

Main collections:
- `hansard-html-snapshots`
- `hansard-pdf-metadata`
- `hansard-parsed-rows`

## Output fields

Parsed rows include:
- `ID`
- `Date`
- `OrderofBusiness`
- `SubjectofBusiness`
- `PersonSpeaking`
- `Intervention`
- `source_url`

## Project structure
.
├── downloader.py
├── incremental_downloader.py
├── parser.py
├── commons.py
├── notebooks/
├── docs/
│   └── Hansard pipeline overview.pdf
└── README.md