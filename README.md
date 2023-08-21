# csp0

![GitHub release (with filter)](https://img.shields.io/github/v/release/dpr-0/csp0)
[![Docker build](https://github.com/dpr-0/csp0/actions/workflows/dockerbuild.yml/badge.svg)](https://github.com/dpr-0/csp0/actions/workflows/dockerbuild.yml)
[![codecov](https://codecov.io/gh/dpr-0/csp0/graph/badge.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)

This is my chat side project type-0 backend code.

## Devlopment Environment

```shell
make dc
make initdb
make migrate
make run
```

### Create .env

Gen RSA Key pair

```shell
openssl genrsa -out key.pem 2048
openssl rsa -in key.pem -pubout -out public.pem
```

paste them to .env

```text
DATABASE_DSN=postgres://postgres:Sfj39w@127.0.0.1:5432/postgres
REDIS_DSN=redis://localhost:6379?decode_responses=True
JWT_LIFETIME=15
PUBLIC_KEY="here"
PRIVATE_KEY="here"
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
