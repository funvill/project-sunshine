# The daily video job: Python (standard library only) and ffmpeg.
# Build once, tag it, and keep using that tag: rebuilding later can pull newer packages.
#   docker build -t sunset-daily:1 nas/
FROM alpine:3.21
RUN apk add --no-cache python3 ffmpeg tzdata
COPY sunset-daily.py /app/sunset-daily.py
ENTRYPOINT ["python3", "/app/sunset-daily.py"]
