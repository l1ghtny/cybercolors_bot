# CyberColors release source selection

The backend, indexer, embeddings, migration, and deployment jobs attach the existing `CyberColors_BackendGit` VCS root at `cybercolors_bot`. Its default branch is `refs/heads/master`. Frontend builds retain the pipeline's tracked main repository.

Use TeamCity's checked-out snapshot, never `git clone master` during a release. Every backend-consuming job checks its Git HEAD against `build.vcs.number.CyberColors_BackendGit`. Image jobs expose `backend_revision`; migration and deployment refuse inconsistent image/source revisions. Backend images also carry the OCI revision label.

Source-aware build reuse is allowed for image jobs. Indexer and embeddings jobs retain their content-hash registry lookup, so a backend-only source change does not require rebuilding unchanged heavy dependencies. Migration and deployment jobs set `allow-reuse: false` because an old successful run does not establish current cluster state.

## Incident regression

On September 20, runs 8892 and 8899 selected backend build 8680/image 255 from September 17 even after new backend commits merged. Those jobs disabled repository tracking and fetched master only inside their scripts. TeamCity therefore had no backend source revision to invalidate reuse. The migration gate rejected image 255 because it did not know the database's current revision `394d5143bacf`; neither run rolled production back. A CLI `--rebuild-deps` request did not fix the incorrect job reuse configuration.

After updating the live pipeline, pull the YAML back and compare it with the reviewed file. Verify the generated jobs attach `CyberColors_BackendGit`, the release uses the expected backend/frontend revisions, migrations complete, and the running workloads and authenticated status API match the release. A queued build or green image build alone is not deployment verification.
