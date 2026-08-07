#!/bin/bash
DITTO_DEVOPS_USER_PW="${DEVOPS_USER}:${DEVOPS_PASSWORD}"
DITTO_CONNECTIONS_BASE_URL="http://${DITTO_HOST}-nginx:${DITTO_NGINX_PORT}/api/2/connections"
DITTO_THINGS_BASE_URL="http://${DITTO_HOST}-nginx:${DITTO_NGINX_PORT}/api/2/things"
HEALTH_URL="http://${DITTO_HOST}-nginx:${DITTO_NGINX_PORT}/status/health"

check_status() {
    exit_code="$1"
    response_body_and_status="$2"

    # 1. Network Level Check: Did curl fail to connect?
    if [ "$exit_code" -ne 0 ]; then
        echo "curl command failed [exit-code: $exit_code]"
        exit 1
    fi

    # Extract HTTP code (last line) and Body (all lines except the last)
    http_code=$(echo "$response_body_and_status" | tail -n1) # get last line
    body=$(echo "$response_body_and_status" | sed '$ d')     # get all but last line
    

    # 2. VALIDATION: Is http_code actually a number?
    case "$http_code" in
        ''|*[!0-9]*) 
            echo "FATAL: Could not retrieve a valid HTTP status code."
            echo "Received status: '$http_code'"
            echo "Full response body: $response_body_and_status"
            exit 1 
            ;;
    esac
    

    # 3. Business Logic Check
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        # Success (200 OK, 201 Created, 204 No Content, etc.)
        echo "SUCCESS: Operation completed [status: $http_code, response: $body]"
    elif [ "$http_code" -eq 409 ]; then
        # Exception: HTTP 409 Conflict is acceptable in this context
        echo "WARNING: Ignoring HTTP response 409 (Conflict/Already Exists) [Response: $body]"
    else 
        # CATCH-ALL: Any other code (3xx, 4xx, 5xx) is treated as a FATAL error.
        echo "ERROR: Request failed or returned unexpected status [status: $http_code, response: $body]"
        exit 1
    fi
}

add_connection_in_ditto() {
    connection_id_prefix="$1"
    http_request_body_file="$2"

    connection_id="${connection_id_prefix}"
    echo "INFO: Adding ditto connection '$connection_id' [URL: ${DITTO_CONNECTIONS_BASE_URL}/${connection_id}]"
    
    # Run curl and append HTTP code on a new line
    response_body_and_status=$(curl --silent --write-out "\n%{http_code}" \
        -X PUT -u "$DITTO_DEVOPS_USER_PW" --header 'Content-Type: application/json' \
        --data-binary "@$http_request_body_file" "${DITTO_CONNECTIONS_BASE_URL}/${connection_id}")
    
    # Pass curl exit code ($?) and the response to the checker
    check_status $? "$response_body_and_status"
}

wait_for_ditto_health() {
    echo "Info: Waiting for Ditto to be UP at ${HEALTH_URL}..."
    
    # Configuration: Try 30 times, waiting 5 seconds between attempts (approx 2.5 mins total)
    max_retries=30
    sleep_seconds=5
    iter=0

    while [ $iter -lt $max_retries ]; do
        # 1. Check Health
        RESPONSE=$(curl --connect-timeout 5 -u "$DITTO_DEVOPS_USER_PW" -s "$HEALTH_URL")
        
        # 2. Validation
        if echo "$RESPONSE" | grep -q '"status"[[:space:]]*:[[:space:]]*"UP"'; then
            echo "SUCCESS: Ditto is UP and ready."
            return 0
        fi

        echo "INFO: Waiting for Ditto... (Attempt $((iter+1))/$max_retries)"
        sleep $sleep_seconds
        iter=$((iter+1))
    done

    echo "FATAL: Timeout waiting for Ditto to become UP. Exiting."
    exit 1
}