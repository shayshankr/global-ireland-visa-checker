# ── Embassy Registry ──────────────────────────────────────────────────────────
# To add a new embassy: add one dict to this list. Nothing else changes.
#
# Fields:
#   name             : Display name shown in the UI
#   url              : Page URL where the decision file link is published
#   type             : "ods" for spreadsheet files | "pdf" for PDF reports
#   keyword          : Text that must appear in the <a> link to identify the right file
#   file_ext         : File extension to match (.ods / .pdf)
#   update_frequency : How often the embassy publishes new data (shown in UI)

EMBASSIES = [
    {
        "name": "New Delhi",
        "url": "https://www.ireland.ie/en/india/newdelhi/services/visas/processing-times-and-decisions/",
        "type": "ods",
        "keyword": "Visa decisions made from",
        "file_ext": ".ods",
        "update_frequency": "Updated daily",
    },
    {
        "name": "Beijing",
        "url": "https://www.ireland.ie/en/china/beijing/services/visas/visa-decisions/",
        "type": "ods",
        "keyword": "Visa Decisions",
        "file_ext": ".ods",
        "update_frequency": "Updated daily",
    },
    {
        "name": "Abuja",
        "url": "https://www.ireland.ie/en/nigeria/abuja/services/visas/weekly-decision-reports/",
        "type": "pdf",
        "keyword": "Abuja Visa Decisions",
        "file_ext": ".pdf",
        "update_frequency": "Updated weekly",
    },
    {
        "name": "Abu Dhabi",
        "url": "https://www.ireland.ie/en/uae/abudhabi/services/visas/weekly-decision-reports/",
        "type": "pdf",
        "keyword": "Abu Dhabi Visa",
        "file_ext": ".pdf",
        "update_frequency": "Updated weekly",
    },
    {
        "name": "Ankara",
        "url": "https://www.ireland.ie/en/turkiye/ankara/services/visas/weekly-decision-report/",
        "type": "pdf",
        "keyword": "Ankara",
        "file_ext": ".pdf",
        "update_frequency": "Updated weekly",
    },
]
