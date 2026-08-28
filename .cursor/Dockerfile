FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System toolchain: Python 3.11 (project pins 3.11 via Pipfile), Pipenv, and a
# local PostgreSQL server so the pipeline can be exercised end-to-end without
# a remote Neon database. Python 3.11 comes from the deadsnakes PPA because
# Ubuntu 24.04 ships 3.12 by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg \
        curl git sudo build-essential \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        python3-pip \
        postgresql postgresql-contrib \
    && pip install --break-system-packages --no-cache-dir pipenv \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 already ships a uid 1000 "ubuntu" user; ensure it exists and can
# use passwordless sudo (needed to start PostgreSQL at boot).
RUN if ! id ubuntu >/dev/null 2>&1; then useradd -m -s /bin/bash -u 1000 ubuntu; fi \
    && echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-ubuntu \
    && chmod 0440 /etc/sudoers.d/90-ubuntu

USER ubuntu
WORKDIR /home/ubuntu

# Keep the virtualenv inside the project directory for predictable paths.
ENV PIPENV_VENV_IN_PROJECT=1
