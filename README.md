# DutchTutor

An AI-based tool to learn Dutch, built around an adaptive tutoring agent that
personalizes pace, correction style, and topics to each learner's profile and
tracks progress across sessions.

## Getting Started

The implementation lives in [`backend/`](./backend) (FastAPI agent service,
pluggable LLM/speech providers) and [`frontend/`](./frontend) (a minimal
chat + voice web UI served by the backend). See
[`backend/README.md`](./backend/README.md) for setup/run/test instructions.

## Project Artifacts

- [`dutch-tutor-agent-spec.md`](./dutch-tutor-agent-spec.md) — the structured
  system prompt / agent specification (source of truth for agent behavior).
- [`lang-skill.md`](./lang-skill.md) — original raw project prompt (history).
- [`lang-skill v1.md`](./lang-skill%20v1.md) — refined prompt draft (history).

## Deploying to Kubernetes (AKS)

The repo includes a [`Dockerfile`](./Dockerfile) and a Helm chart in
[`charts/dutchtutor`](./charts/dutchtutor). The app keeps learner data as
JSON files, so the chart runs **one replica** on a persistent Azure Disk, and
serves it over HTTPS (browsers only allow the microphone on secure sites).

```bash
# 1. Build the image in your registry (and attach the ACR to AKS once)
az acr build --registry <acr> --image dutchtutor:1.0.0 .
az aks update -g <rg> -n <cluster> --attach-acr <acr>
#    Or build locally and push. On Apple Silicon, build for the nodes' CPU,
#    or pods fail with "exec format error":
docker buildx build --platform linux/amd64 -t <registry>/dutchtutor:<new-tag> --push .

# 2. Keys go in a Secret you create (never in values files)
kubectl create namespace dutchtutor
kubectl -n dutchtutor create secret generic dutchtutor-keys \
  --from-literal=AZURE_OPENAI_API_KEY=... \
  --from-literal=AZURE_SPEECH_KEY=... \
  --from-literal=AUTH_SECRET="$(openssl rand -hex 32)"

# 3. Install
helm upgrade --install tutor charts/dutchtutor -n dutchtutor \
  --set image.repository=<acr>.azurecr.io/dutchtutor \
  --set secret.existingSecret=dutchtutor-keys \
  --set ingress.host=tutor.example.com \
  --set config.AZURE_OPENAI_ENDPOINT=https://<resource>.services.ai.azure.com/ \
  --set config.AZURE_OPENAI_DEPLOYMENT=<deployment> \
  --set config.AZURE_SPEECH_REGION=<region> \
  --set config.AZURE_SPEECH_ENDPOINT=https://<resource>.services.ai.azure.com/
```

See [`values.yaml`](./charts/dutchtutor/values.yaml) for TLS (cert-manager or
Key Vault), ingress class, storage and resource settings. Back up the data
disk (Azure Disk snapshots or Azure Backup for AKS) — it holds all learner
progress — and claim existing user ids such as `demo-user` before sharing the
URL.
