{{/*
Expand the name of the chart.
*/}}
{{- define "opentwins.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "opentwins.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}



{{- define "installation.name" -}}
{{- default .Release.Name -}}
{{- end -}}



{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "opentwins.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "opentwins.labels" -}}
helm.sh/chart: {{ include "opentwins.chart" . }}
{{ include "opentwins.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "opentwins.selectorLabels" -}}
app.kubernetes.io/name: {{ include "opentwins.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "opentwins.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "opentwins.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the full name of the Hono sub chart.
*/}}
{{- define "opentwins.hono.fullname" -}}
  {{- if .Values.hono.fullnameOverride }}
    {{- .Values.hono.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default "hono" .Values.hono.nameOverride }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end -}}
{{- end -}}

{{/*
Get the full name of the Ditto sub chart.
*/}}
{{- define "opentwins.ditto.fullname" -}}
  {{- if .Values.ditto.fullnameOverride }}
    {{- .Values.ditto.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default "ditto" .Values.ditto.nameOverride }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end -}}
{{- end -}}

{{/*
Get the full name of the Mosquitto sub chart.
*/}}
{{- define "opentwins.mosquitto.fullname" -}}
  {{- if .Values.mosquitto.fullnameOverride }}
    {{- .Values.mosquitto.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default "mosquitto" .Values.mosquitto.nameOverride }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end -}}
{{- end -}}

{{/*
Get the full name of the InfluxDB2 sub chart.
*/}}
{{- define "opentwins.influxdb2.fullname" -}}
  {{- if .Values.influxdb2.fullnameOverride }}
    {{- .Values.influxdb2.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default "influxdb2" .Values.influxdb2.nameOverride }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end -}}
{{- end -}}


{{/*
Get the full name of the MongoDB sub chart.
*/}}
{{- define "opentwins.mongodb.fullname" -}}
  {{- if .Values.mongodb.fullnameOverride }}
    {{- .Values.mongodb.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
    {{- $name := default "mongodb" .Values.mongodb.nameOverride }}
    {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end -}}
{{- end -}}

{{/*
Get the full name of Extended API.
*/}}
{{- define "opentwins.extendedAPI.fullname" -}}
  {{- printf "%s-ditto-extended-api" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end -}}

{{/* Common labels */}}
{{- define "kafkaml.labels" -}}
app.kubernetes.io/name: kafkaml
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Base name with kafkaml middle part */}}
{{- define "kafkaml.fullname" -}}
{{- printf "%s-kafkaml-%s" .Release.Name .Component -}}
{{- end }}