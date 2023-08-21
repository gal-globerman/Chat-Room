# csp0

[![codecov](https://codecov.io/gh/dpr-0/csp0/graph/badge.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)

## Minimal container vm

Colima and Testcontainer docker sock problem

<https://github.com/abiosoft/colima/blob/main/docs/FAQ.md#cannot-connect-to-the-docker-daemon-at-unixvarrundockersock-is-the-docker-daemon-running>

## Create dev env

```shell
docker compose up -d
make initdb
```

## Gen RSA Key pair

```shell
openssl genrsa -out key.pem 2048
openssl rsa -in key.pem -pubout -out public.pem
```

## Test

### Test Coverage

[![codecov](https://codecov.io/gh/dpr-0/csp0/graph/badge.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)
[![codecov](https://codecov.io/gh/dpr-0/csp0/graphs/icicle.svg?token=D3D2ST9HDG)](https://codecov.io/gh/dpr-0/csp0)
