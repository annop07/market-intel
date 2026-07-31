# Static Go binary in a scratch-adjacent image: ~15 MB, no toolchain shipped.
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/collect ./cmd/collect

FROM alpine:3.22
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 collector
COPY --from=build /out/collect /usr/local/bin/collect
USER collector
WORKDIR /data
ENTRYPOINT ["collect"]
CMD ["-source", "all", "-out", "/data/raw/{source}.jsonl"]
