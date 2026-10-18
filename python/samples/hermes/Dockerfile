FROM docker.io/nousresearch/hermes-agent@sha256:c56a1bd108e94c850cc785b5c7142b6f1633066b2306f15a9438d698a3be0077
USER root
# Bundle the same runtime contracts as the controller built from this checkout.
COPY packages/kagent-proto /tmp/kagent/kagent-proto
COPY packages/kagent-core /tmp/kagent/kagent-core
RUN /opt/hermes/.venv/bin/python -m ensurepip && \
    /opt/hermes/.venv/bin/python -m pip install --no-cache-dir 'a2a-sdk==1.1.5' /tmp/kagent/kagent-proto /tmp/kagent/kagent-core && \
    rm -rf /tmp/kagent
COPY samples/hermes/adapter.py /opt/kagent-hermes/adapter.py
ENV HERMES_HOME=/data/hermes HERMES_WRITE_SAFE_ROOT=/data
ENV TERMINAL_ENV=local TERMINAL_CWD=/data/workspace
ENV PYTHONPATH=/opt/hermes
WORKDIR /opt/hermes
EXPOSE 80 8081
ENTRYPOINT ["/opt/hermes/.venv/bin/python", "/opt/kagent-hermes/adapter.py"]
