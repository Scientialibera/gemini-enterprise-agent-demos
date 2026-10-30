"""Tools the demo agents share: read-only BigQuery, Gmail delivery and PDF styling.

Everything here runs as the agent's own Agent Identity, so no user OAuth consent,
connector or Google Workspace account is needed:

    bigquery    run one read-only SELECT against an allowlisted set of datasets
    mailer      send an HTML email with attachments through a Gmail app password
    pdf         the shared report theme: palette, page frame, tables, light markdown
"""
