#!/bin/sh
source ditto-connection.sh

#######################################################################################################################################
# This code is based on the file: https://github.com/eclipse/packages/blob/master/packages/cloud2edge/post-install/post-install.sh
#######################################################################################################################################

# Variables
# ----------------------------------------------
MOSQUITTO_BASE_URL="tcp://${MOSQUITTO_HOST}:1883"
FILENAME=mosquitto-source-connection.json

# Main code
# ----------------------------------------------
wait_for_ditto_health

{{- if .Values.mosquitto.enabled }}
echo "Mosquitto base url: $MOSQUITTO_BASE_URL"
add_connection_in_ditto "mosquitto-source-connection" $FILENAME
echo "DONE"
{{- end}}

{{- if .Values.externalMosquitto }}
  {{- range $v := .Values.externalMosquitto }}
echo "Mosquitto base url: {{$v.uri}}"
echo 's#"name": [^,]*#"name": "{{$v.name}}"#'
echo 's#"uri": [^,]*#"uri": "{{$v.uri}}"#'
echo 's~"addresses":\[.*\]~"addresses": ["{{ join "\",\"" $v.addresses }}"]~'
sed 's#"name": [^,]*#"name": "{{$v.name}}"#' mosquitto-source-connection.json > datos1.json
sed 's#"uri": [^,]*#"uri": "{{$v.uri}}"#' datos1.json > datos2.json
sed 's~"addresses":\[.*\]~"addresses":["{{ join "\",\"" $v.addresses }}"]~' datos2.json > datos3.json
echo $(cat datos3.json)
add_connection_in_ditto "{{$v.name}}" "datos3.json"
echo "DONE"
  {{- end }}
{{- end }}