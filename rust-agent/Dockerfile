# cargo-chef multi-stage build — first build: 15-20min, rebuilds: ~3min
# Stage 1: base image with build deps + cargo-chef installed
FROM rust:1.88-slim AS chef
WORKDIR /app
RUN cargo install cargo-chef --locked
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    libavcodec-dev \
    libavformat-dev \
    libavfilter-dev \
    libavdevice-dev \
    libswscale-dev \
    libswresample-dev \
    clang \
    nasm \
    yasm \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: generate dependency recipe (only Cargo.toml/lock — no source code)
FROM chef AS planner
COPY Cargo.toml Cargo.lock* ./
RUN mkdir -p src && echo "fn main() {}" > src/main.rs
RUN cargo chef prepare --recipe-path recipe.json

# Stage 3: compile dependencies only (this layer is cached unless Cargo.toml changes)
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# Now add real source — only this step re-runs on code changes
COPY src ./src
RUN cargo build --release

# Stage 4: minimal runtime image
FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libssl3 \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/viraclip-agent /usr/local/bin/
COPY --from=builder /app/target/release/viraclip-tui /usr/local/bin/

RUN mkdir -p /app/temp
WORKDIR /app

ENV RUST_AGENT_PORT=8001
ENV WORKDIR=/app/temp
ENV RUST_LOG=info

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8001/agent/health || exit 1

EXPOSE 8001
CMD ["viraclip-agent"]
