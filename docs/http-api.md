# HTTP API

`contribution_router` adds two endpoints to your backend. The browser
uses the first endpoint to check the files while the contributor
corrects them. It uses the second endpoint to submit them. This page
gives the request format, each status code, the limits, and a browser
client.

## The endpoints

| Endpoint              | Purpose                                     |
| --------------------- | ------------------------------------------- |
| `POST /validate`      | Check the files. Nothing is stored.         |
| `POST /contributions` | Check the files again, then submit them.    |
| `GET /contributions/{id}/state` | The state of a draft. Only with `public_state`. |

The two endpoints take `multipart/form-data`. Each file is one part in
the field `files`. The file name of the part is the relative path of
the file, for example `my-walls/02_fd_curve/fd_curve_A1.csv`. A part
can also be a `.zip` or a `.tar.gz` archive. The intake expands it.

`POST /contributions` also takes these text fields:

| Field         | Rule                                       |
| ------------- | ------------------------------------------ |
| `name`        | Required, one line, 1 to 200 characters    |
| `email`       | Required, a valid email address            |
| `institution` | Required, one line, 1 to 200 characters    |
| `orcid`       | Optional, for example `0000-0002-1825-0097` |
| `note`        | Optional, up to 2000 characters            |

An empty optional field is the same as no field. With
`contributor=Model`, the router reads the fields of your model instead.

The browser can also send one field `contributor` with a JSON object,
for example `{"name": "Ada", "email": "ada@example.org"}`. Then the
router ignores the other contributor fields. JSON that is not valid
answers 422.

The state route answers 200 with `{"id": ..., "state": ...}`, or 404.
It returns no contributor data.

## Status codes

The body of an answer has one of two shapes. A report is
`{"valid": bool, "issues": [Issue, ...]}`. An error is
`{"detail": ...}`.

| Endpoint              | Status | Body                         | Cause                                      |
| --------------------- | ------ | ---------------------------- | ------------------------------------------ |
| `POST /validate`      | 200    | Report                       | The check ran. Read `valid`.               |
| `POST /validate`      | 400    | `{"detail": str}`            | The upload is refused, for example a bad path or a large file |
| `POST /validate`      | 503    | `{"detail": str}`            | The validator raised an exception          |
| `POST /contributions` | 201    | Report, with `id` and `url`  | The review request is open                 |
| `POST /contributions` | 400    | `{"detail": str}`            | The upload is refused                      |
| `POST /contributions` | 422    | Report                       | The data has one or more errors            |
| `POST /contributions` | 422    | `{"detail": [error, ...]}`   | A contributor field is not valid           |
| `POST /contributions` | 429    | `{"detail": str}`            | The rate limit or the review-queue limit   |
| `POST /contributions` | 502    | `{"detail": str}`            | The sink failed. Nothing is submitted.     |
| `POST /contributions` | 503    | `{"detail": str}`            | The router has `enabled=False`             |

In a 422 answer, `issues` tells you that the data has errors. A
`detail` tells you that a contributor field has an error.

## Limits

The router protects the review queue with two limits. Both give 429.

- Rate limit: each client can submit 10 contributions in each hour.
  Change it with `rate_limit=(attempts, seconds)`.
- Review-queue limit: if 25 contributions wait for review, the router
  refuses new ones. Change it with `Pipeline(..., max_open=25)`.

The router identifies a client by the last entry of the
`X-Forwarded-For` header, else by the peer address. To change this,
give a function to `client_key`.

> Note: The rate limit is kept in the memory of the process. If you
> run more than one replica, each replica counts separately. A restart
> sets the counts to zero.

The intake also has size limits: `max_files=500`,
`max_file_bytes` of 50 MiB, and `max_total_bytes` of 200 MiB. Set a
limit on the request body at the ingress too.

## A browser client

Use relative paths. This example assumes that the router is under
`/api`.

```javascript
async function post(path, files, fields = {}) {
  const form = new FormData()
  for (const { path: name, file } of files) form.append('files', file, name)
  for (const [key, value] of Object.entries(fields)) {
    if (value.trim()) form.append(key, value.trim())
  }
  const response = await fetch('/api' + path, { method: 'POST', body: form })
  return { status: response.status, body: await response.json() }
}

// files: [{ path: 'my-walls/database.csv', file: File }, ...]
const check = await post('/validate', files)
if (check.status === 200 && check.body.valid) {
  const sent = await post('/contributions', files, {
    name: 'Ada Lovelace',
    email: 'ada@example.org',
    institution: 'EPFL',
  })
  if (sent.status === 201) console.log('Review request:', sent.body.url)
}
```

For a folder, `File.webkitRelativePath` gives the relative path. The
eesd project has a complete client in
[contribute.ts](https://github.com/EPFL-ENAC/eesd-modern-masonry-walls-db/blob/dev/frontend/src/api/contribute.ts).

## Next step

Read [GitHub App](github-app.md) to get the credentials that the sink
needs.
