# Streamlit Community Cloud

Deploy repository `Epsilon3096/monsoon-rehearsal`, branch `main`, entrypoint
`app.py`. In **Advanced settings**, select **Python 3.12**, matching the local
verified environment. The supported project range is Python 3.11–3.13;
Python 3.14 is not supported by this release.

The root `requirements.txt` delegates to `requirements.lock.txt`, preserving
the release's exact dependency pins. Streamlit discovers `requirements.txt`
before `pyproject.toml`; this avoids attempting to install this setuptools
project through Poetry. Do not remove the Python upper bound to hide a runtime
mismatch.

If an existing deployment reports Python 3.14, open its **Settings → General**,
set **Python version** to **3.12**, and save changes. This control was available
in the signed-in Community Cloud interface on 20 October 2026. Rebooting or
changing the requirements file alone does not select a different interpreter.
The linked Python-version documentation still describes deleting and
recreating the app; prefer the in-place setting when the interface offers it.

Official instructions:

- [Deploy an app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Dependency discovery](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)
- [Change the Python version](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/upgrade-python)

## Hosted verification

Successful dependency installation is only the first check. Open the deployed
app in a signed-out browser, inspect Demonstration and Evidence, and run a
rehearsal and its plan audit. Retain failed hydraulic/location checks as failed.
Verify native SWMM execution on the Linux host; Windows verification alone
does not certify the hosted runtime.

This release's SQLite workflow and research accounts were designed for local
use. Before sharing an unrestricted public deployment, review visitor/session
isolation and storage persistence. Cloud restart behaviour must not be
represented as durable operational record keeping. No real maintenance should
be authorised by this synthetic demonstration.
