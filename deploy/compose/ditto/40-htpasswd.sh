#!/bin/sh
# Generate the Ditto nginx basic-auth file from the environment at container
# start, so no credential is ever baked into the repository. {PLAIN} is a
# documented nginx auth_basic scheme; the same values already live in .env.
set -eu
: "${DITTO_PASSWORD:?DITTO_PASSWORD is not set}"
: "${DITTO_DEVOPS_PASSWORD:?DITTO_DEVOPS_PASSWORD is not set}"
umask 077
printf 'ditto:{PLAIN}%s\ndevops:{PLAIN}%s\n' "$DITTO_PASSWORD" "$DITTO_DEVOPS_PASSWORD" > /etc/nginx/nginx.htpasswd
chown nginx /etc/nginx/nginx.htpasswd
