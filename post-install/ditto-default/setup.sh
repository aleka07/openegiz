#!/bin/sh
source ditto-connection.sh

DITTO_DEVOPS_USER_PW="{{ .Values.ditto.global.basicAuthUsers.devops.user }}:{{ .Values.ditto.global.basicAuthUsers.devops.password }}"
DITTO_BASIC_USER_PW="{{.Values.ditto.global.basicAuthUsers.ditto.user}}:{{.Values.ditto.global.basicAuthUsers.ditto.password}}"
DITTO_POLICIES_BASE_URL="http://{{ include "opentwins.ditto.fullname" . }}-nginx:{{ .Values.ditto.nginx.service.port }}/api/2/policies"

wait_for_ditto_health

echo "Adding default policy [URL: ${DITTO_POLICIES_BASE_URL}/default:basic_policy]"
response_body_and_status=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -u "$DITTO_BASIC_USER_PW" --header 'Content-Type: application/json' \
    --data-binary "@basic-policy.json" "${DITTO_POLICIES_BASE_URL}/default:basic_policy")
check_status $? "$response_body_and_status"
