FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash git curl ca-certificates openssh-client libatomic1 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash hermes
USER hermes
ENV PATH=/home/hermes/.local/bin:$PATH
# Bump this hash only after reading the new install.sh (the build fails if upstream changed it).
ARG INSTALL_SHA256=abf338605dae6dd28d101673ac6aed7995c955745db46d47676bc591a7957209
RUN curl -fsSL -o /tmp/install.sh https://hermes-agent.nousresearch.com/install.sh \
    && echo "$INSTALL_SHA256  /tmp/install.sh" | sha256sum -c - \
    && bash /tmp/install.sh --non-interactive --skip-browser --skip-computer-use \
    && rm -f /tmp/install.sh
USER root
# The install stays in the image; state (config, memory, sessions, skills) lives in the /data volume.
ENV HERMES_HOME=/data/hermes HERMES_RUNTIME_DIR=/home/hermes/.hermes/tools
COPY docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
