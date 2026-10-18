# Hermes BYO runtime

This adapter runs NousResearch Hermes inside a kagent Substrate Actor. It uses
kagent-core's A2A gRPC handler and controller-backed TaskStore. Hermes private
conversation history and home directory live under `/data/hermes`; work products
live under `/data/workspace`.

The image bundles kagent-core and kagent-proto from the same checkout as the
controller, matching its `kagent.api.v1alpha1.TaskStoreService` wire API. The
publishing workflow builds and tests both from one commit.

The initial adapter supports text input, final-answer artifacts, cancellation,
OpenAI Chat Completions ModelConfigs, and Hermes terminal/file tools. It does not
translate AgentTemplate MCP, plugin, or skill bindings, expose Hermes's web UI,
or stream individual text deltas. Working and completion events are streamed.
The default iteration limit is 30. Runtime model credentials use kagent's existing
egress injection; no real API key belongs in the image or Harness environment.

Build from the repository root, using an authenticated registry repository:

```sh
export HERMES_REPOSITORY=ghcr.io/YOUR_ACCOUNT/hermes-kagent
docker build --platform linux/arm64 -t "$HERMES_REPOSITORY:v2" \
  -f python/samples/hermes/Dockerfile python
docker push "$HERMES_REPOSITORY:v2"
docker buildx imagetools inspect "$HERMES_REPOSITORY:v2"
```

`resources.yaml` pins the published `ghcr.io/spichen/hermes-kagent:v2` digest.
When rebuilding, update it to the new `repository@sha256:digest` reference.
Check the namespace, WorkerPool, snapshot
location, and ModelConfig against the intended cluster before applying. The
included resources are prepared for the `oracle-oke` cluster's `kagent` namespace.

```sh
kubectl --context oracle-oke apply --dry-run=server -f rendered-resources.yaml
kubectl --context oracle-oke apply -f rendered-resources.yaml
kubectl --context oracle-oke -n kagent wait --for=condition=Ready \
  agent/hermes-agent --timeout=300s
```

Then use the deployment's configured kagent CLI connection to create a session
and invoke it. Verify a second turn remembers the first, a terminal operation
works, cancellation finishes, and suspend/resume retains state before relying
on the deployment.

Tests run inside the built image without real model credentials:

```sh
docker run --rm --entrypoint /opt/hermes/.venv/bin/python \
  -v "$PWD/python/samples/hermes:/tests:ro" -w /tests \
  "$HERMES_REPOSITORY:v2" -m unittest -v test_adapter
docker run --rm --entrypoint /opt/hermes/.venv/bin/python \
  -e OPENAI_API_KEY=smoke-placeholder \
  -v "$PWD/python/samples/hermes:/tests:ro" -w /tests \
  "$HERMES_REPOSITORY:v2" smoke_test.py
```

The smoke test exercises the actual Hermes execution loop against a local mock
model and verifies conversation recovery after replacing the adapter executor.
It does not establish cluster or live-provider compatibility.
