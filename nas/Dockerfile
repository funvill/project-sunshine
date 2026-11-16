# The daily video job: Python (standard library only) and ffmpeg.
# Build once, tag it, and keep using that tag: rebuilding later can pull newer packages.
#   docker build -t sunset-daily:1 nas/
#
# The base is pinned by digest: alpine:3.21.10, the multi-arch index, looked up on Docker Hub on
# 2026-11-15 (it was also alpine:3.21 that day). The packages are pinned to the versions in the
# Alpine 3.21 index that day, the same for x86_64 and aarch64. Alpine keeps only the newest build
# of each package in a branch, so once one of these is replaced the build fails here. That is on
# purpose: pick the new versions deliberately (`apk policy <name>` in the new base), bump the tag,
# and check America/Vancouver in the new tzdata (the overlay times and VIDEO_START_LOCAL depend on it).
#
# Keep a copy of the built image beside the Pi's SD images, so it can be run again without
# rebuilding:
#   docker save sunset-daily:1 | gzip > sunset-daily-1.tar.gz
#   docker load < sunset-daily-1.tar.gz
FROM alpine:3.21.10@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab
RUN apk add --no-cache python3=3.12.16-r0 ffmpeg=6.1.2-r1 tzdata=2026f-r0 font-dejavu=2.37-r5
COPY sunset-daily.py /app/sunset-daily.py
ENTRYPOINT ["python3", "/app/sunset-daily.py"]
