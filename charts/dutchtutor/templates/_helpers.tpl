{{- define "dutchtutor.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "dutchtutor.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "dutchtutor.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "dutchtutor.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "dutchtutor.secretName" -}}
{{- default (include "dutchtutor.fullname" .) .Values.secret.existingSecret -}}
{{- end -}}

{{- define "dutchtutor.claimName" -}}
{{- default (printf "%s-data" (include "dutchtutor.fullname" .)) .Values.persistence.existingClaim -}}
{{- end -}}
