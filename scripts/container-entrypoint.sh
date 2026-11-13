#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    install -d -o appuser -g appuser -m 0700 /run/inspection-secrets
    for name in \
        supabase_storage_email \
        supabase_storage_password \
        slurm_identity_key \
        slurm_known_hosts
    do
        source="/run/secrets/$name"
        if [ -f "$source" ]; then
            install -o appuser -g appuser -m 0400 \
                "$source" "/run/inspection-secrets/$name"
        fi
    done
    exec gosu appuser "$@"
fi

exec "$@"
