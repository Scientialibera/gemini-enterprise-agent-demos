"""Bootstrap values this workflow resolves once at import.

Two ways to run, chosen by the deployment:

* With a Gemini Enterprise authorization, the performance Google Sheet is read
  as the signed-in user.
* Without one, the performance workbook is a ``gs://`` .xlsx read as the
  runtime's own Agent Identity, and the report is emailed as a PDF. This needs no
  user consent or Google Workspace account.

The third-party API keys (BLS, FRED, New York Times, Google Places) and the Gmail
app password are read from Secret Manager under the runtime's own identity;
``<NAME>_SECRET`` names each secret.
"""

from __future__ import annotations

from gemini_shared import get_bootstrap_settings

BOOTSTRAP = get_bootstrap_settings()
USER_AUTHORIZATION_ID = BOOTSTRAP.gemini_enterprise_authorization_id
