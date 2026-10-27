# Browser-based attachment tracker

This is a small, standalone local prototype. It does not import the existing
desktop launcher or the incomplete FastAPI backend.

## Run it

From this folder, run:

```powershell
python web_server.py
```

If PowerShell says `python` is not recognized in this environment, run:

```powershell
& 'C:\Users\Administrator\.local\bin\python3.14.exe' web_server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. Students use
the public form at `/`. Staff use `/staff`. On first visit to the staff portal,
create the administrator account; the account can then sign in to enter
applications, view all submissions, and change review statuses.

The app uses only the Python standard library and stores applications and
password hashes in `attachment_web.db`. Set `PORT` or `ATTACHMENT_WEB_DB`
before starting the server to change the port or database file. Existing
application records in that database are preserved when the new staff tables
are initialized.

## Included in this first version

- Submit student attachment applications without a student account.
- Require staff sign-in to view applications or change review statuses.
- Allow signed-in staff to enter applications on students' behalf.
- Create the initial staff account once from the staff portal.
- Validate required fields, email format, and the placement date range.

## Important limitations

This remains a local prototype. It binds to `127.0.0.1`; do not expose it
directly to a public/shared network or use it for real student records. The
public student form does not require an account, so anyone who can reach the
site can submit. Staff-only records require a password and a same-origin
session cookie. A production system still needs HTTPS, deployment hardening,
data-protection controls, backups, and integration with the original
application models. The existing desktop and FastAPI code cannot yet be
integrated because supporting modules such as `models.py` and `database.py`
were not available in the workspace.

## Tests

Run the standard-library integration tests with:

```powershell
python -m unittest discover -s tests -v
```
