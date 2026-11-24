# Provenance: fastapi_template

| Field | Value |
|---|---|
| Upstream | https://github.com/fastapi/full-stack-fastapi-template |
| Commit | `b1125d8839482cb7bbae603ddc6d0081bf87532e` (default branch `master`) |
| Subset | `backend/` only (byte-identical copy), plus the upstream root `LICENSE` |
| License | MIT, Copyright (c) 2019 Sebastián Ramírez — see `LICENSE` |
| Retrieved | 2026-10-26 from `https://codeload.github.com/fastapi/full-stack-fastapi-template/tar.gz/<commit>` |
| Integrity | `content_sha256` in `benchmark.json` = SHA-256 over sorted `path\0sha256(file)\n` lines of `backend/**` |

Vendored so the evaluation runs offline and reproducibly. This copy is test data: it is never imported, executed or packaged into the Raven image (`.dockerignore` excludes `backend/evals`).
`python -m evals verify-sources --network` re-downloads the upstream tarball and checks that this subset is still byte-identical.
