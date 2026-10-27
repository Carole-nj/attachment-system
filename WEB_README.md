# Browser-based attachment tracker

This is a small, standalone local prototype. It does not import the existing
desktop launcher or the incomplete FastAPI backend.

## Run it

From this folder, run:

```powershell
python web_server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. The app uses
only the Python standard library and stores applications in
`attachment_web.db`. Set `PORT` or `ATTACHMENT_WEB_DB` before starting the
server to change the port or database file.

## Included in this first version

- Submit student attachment applications.
- View saved applications and review their status as pending, approved, or
  rejected.
- Validate required fields, email format, and the placement date range.

## Important limitations

This prototype has no sign-in, authorization, file uploads, or role separation.
It binds to `127.0.0.1` and is intended only for local evaluation. Do not expose
it to a public/shared network or use it for real student records. A production
system needs authenticated roles, secure deployment, data-protection controls,
backups, and integration with the original application models. The existing
desktop and FastAPI code cannot yet be integrated because supporting modules
such as `models.py` and `database.py` were not available in the workspace.

## Tests

Run the standard-library integration tests with:

```powershell
python -m unittest discover -s tests -v
```
