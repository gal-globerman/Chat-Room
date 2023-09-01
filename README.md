# csp0

![GitHub release (with filter)](https://img.shields.io/github/v/release/dpr-0/csp0)
[![Docker build](https://github.com/dpr-0/csp0/actions/workflows/dockerbuild.yml/badge.svg)](https://github.com/dpr-0/csp0/actions/workflows/dockerbuild.yml)
[![codecov](https://codecov.io/gh/dpr-0/csp0/graph/badge.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)

This is my chat side project type-0: A Random Chat Room implemented by FastAPI.

Implemented features:

1. JWT authentication
1. User registration
1. User match a random user and unmatch (Redis set)
1. User send and recieve message (Redis stream)
1. User recieve notification (Redis stream)

This project are implemented base on:

1. Clean architecture and Domain-Drvien Design concept
1. Message bus

## Demo


https://github.com/dpr-0/csp0/assets/75435041/b4ea6bb6-a2b4-4a36-b00c-98bc255d5636


## Setup Devlopment Environment

### Docker Compose

```shell
make dc
```

### Create .env file

Gen RSA Key pair

```shell
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

paste them to .env

```text
DATABASE_DSN=postgres://postgres:Sfj39w@127.0.0.1:5432/postgres
REDIS_DSN=redis://localhost:6379?decode_responses=True
PUBLIC_KEY="here"
PRIVATE_KEY="here"
```

### Poetry

```shell
poetry install
```

### Local Run Server

Create DB schema (first time)

```shell
aerich upgrade
```

Run Server

```shell
make run
```

## Test

```shell
make test
```

### Test Coverage

[![codecov](https://codecov.io/gh/dpr-0/csp0/graph/badge.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)
[![codecov](https://codecov.io/gh/dpr-0/csp0/graphs/icicle.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)

## If use Minimal container vm

[Colima and Testcontainer docker sock problem](<https://github.com/abiosoft/colima/blob/main/docs/FAQ.md#cannot-connect-to-the-docker-daemon-at-unixvarrundockersock-is-the-docker-daemon-running>
)
