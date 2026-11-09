ARG RCLONE_VERSION=1.75.2
FROM rclone/rclone:${RCLONE_VERSION} AS rclone
FROM python:3.13-alpine
ARG VERSION=0.1.0
LABEL org.opencontainers.image.title="KDBX Backup" \
      org.opencontainers.image.description="Append-only KDBX snapshots with verified multi-cloud backup" \
      org.opencontainers.image.version=${VERSION} \
      org.opencontainers.image.licenses="MIT"
RUN apk add --no-cache ca-certificates tzdata
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY LICENSE third_party/rclone-LICENSE /usr/share/licenses/kdbx-backup/
WORKDIR /app
COPY src/kdbx_backup ./kdbx_backup
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC \
    RCLONE_CONFIG=/secrets/rclone/rclone.conf
ENTRYPOINT ["python", "-m", "kdbx_backup.service"]
