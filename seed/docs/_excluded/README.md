# Excluded documents (P3)

Downloaded with the corpus but **not ingested**: `scripts/check_docs.py` marked them SUSPICIOUS.
Both are scanned Marathi PDFs without a text layer; docling's OCR (RapidOCR, Chinese/English
models) turns the Devanagari into Chinese characters and Latin noise.

| File | Source | Reason |
|---|---|---|
| mh_coop_election_panel_guidelines_mr.pdf | https://sahakarayukta.maharashtra.gov.in/site/upload/documents/Guidelines%20for%20the%20Panel%20of%20Election_02_12_19.pdf | scanned, 267 chars for 3 pages |
| mh_coop_policy_press_note_mr.pdf | https://sahakarayukta.maharashtra.gov.in/site/upload/documents/press%20note_1.pdf | scanned, OCR output is Chinese characters |
