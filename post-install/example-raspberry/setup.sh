#!/bin/sh
source ditto-connection.sh

#######################################################################################################################################
# This code is based on the file: https://github.com/eclipse/packages/blob/master/packages/cloud2edge/post-install/post-install.sh
#######################################################################################################################################

# --- Variables ---
EXTENDED_API_BASE_URL="http://${EXTENDED_API_HOST}:${EXTENDED_API_PORT}/api"
DITTO_DEVOPS_USER_PW="${DEVOPS_USER}:${DEVOPS_PASSWORD}"
DITTO_BASIC_USER_PW="${DITTO_USER}:${DITTO_PASSWORD}"
DITTO_POLICIES_BASE_URL="http://${DITTO_HOST}-nginx:${DITTO_NGINX_PORT}/api/2/policies"


echo "INFO: Extended API Base URL: ${EXTENDED_API_BASE_URL}"

# --- Main Execution ---
wait_for_ditto_health

# 1. Add Policy
echo "INFO: Adding example policy [URL: ${DITTO_POLICIES_BASE_URL}/example:very_insecure_policy]"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -u "$DITTO_BASIC_USER_PW" --header 'Content-Type: application/json' \
    --data-binary "@policy.json" "${DITTO_POLICIES_BASE_URL}/example:very_insecure_policy")
check_status $? "$response"


# 2. Create Raspberry Type
echo "INFO: Creating raspberry type"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -H "Content-Type: application/json" \
    -d @type_raspberry.json \
    "${EXTENDED_API_BASE_URL}/types/example:raspberry_type")
check_status $? "$response"


# 3. Create Raspberry Twin
echo "INFO: Creating raspberry twin"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    "${EXTENDED_API_BASE_URL}/types/example:raspberry_type/create/example:raspberry")
check_status $? "$response"


# 4. Create DHT22 Type
echo "INFO: Creating DHT22 type"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -H "Content-Type: application/json" \
    -d @type_DHT22.json \
    "${EXTENDED_API_BASE_URL}/types/example:raspberry_type/children/example:DHT22/2")
check_status $? "$response"


# 5. Create DHT22_1 Twin
echo "INFO: Creating DHT22_1 twin"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    "${EXTENDED_API_BASE_URL}/types/example:DHT22/create/raspberry:DHT22_1")
check_status $? "$response"


# 6. Create DHT22_2 Twin
echo "INFO: Creating DHT22_2 twin"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    "${EXTENDED_API_BASE_URL}/types/example:DHT22/create/raspberry:DHT22_2")
check_status $? "$response"


# 7. Assign to Parent (Relation)
echo "INFO: Assigning DHT22_1 to parent raspberry"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -H "Content-Type: application/json" \
    "${EXTENDED_API_BASE_URL}/twins/example:raspberry/children/raspberry:DHT22_1")
check_status $? "$response"

echo "INFO: Assigning DHT22_2 to parent raspberry"
response=$(curl --silent --write-out "\n%{http_code}" \
    -X PUT -H "Content-Type: application/json" \
    "${EXTENDED_API_BASE_URL}/twins/example:raspberry/children/raspberry:DHT22_2")
check_status $? "$response"


# 8. Connection Setup
echo "INFO: Setting up connection with raspberry simulator"
add_connection_in_ditto "example-raspberry-source-connection" "connection.json"

echo "SUCCESS: Setup completed successfully."