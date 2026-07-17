# Enterprise Deployment & Kubernetes Guide

This document outlines the standard deployment practices for the Laguna AI Line Balancing application, with a deep dive into Docker Compose versus Kubernetes, and a full guide to testing Kubernetes locally.

---

## 1. The Recommended Deployment Strategy

For the Laguna AI application (Django, Celery ML workers, Postgres, Redis, and React Vite Frontend), the most cost-effective and robust deployment strategy is to **decouple the frontend and backend**.

### Frontend (React/Vite)
- **Host:** Vercel (Recommended), Netlify, or AWS Amplify.
- **Why:** Vercel serves static files globally on an Edge CDN. It is 100% free, blazingly fast, and automatically builds your application from GitHub without any manual server configuration.
- **How:** Run `npm run build` or let Vercel trigger it on push. Ensure `VITE_API_BASE_URL` points to your backend.

### Backend (Django + ML + Postgres + Redis)
- **Host:** Azure Virtual Machine (Linux Ubuntu) or DigitalOcean Droplet ($10-$15/month).
- **Why:** Machine Learning tasks (via Celery workers) require continuous background processing and high memory overhead, which free tiers (like Render or Heroku's free tiers) block or put to "sleep." 
- **How:** 
  ```bash
  # On your Azure/DigitalOcean VM:
  sudo apt install docker.io docker-compose
  git clone <repo>
  cd laguna-ai-line-balancing
  sudo ./scripts/start.sh --prod
  ```

---

## 2. Docker Compose vs. Kubernetes

While `docker-compose` is excellent for single-server setups, Enterprise applications often migrate to **Kubernetes (K8s)**. Here is the distinction:

| Feature | Docker Compose (Single VM) | Kubernetes (Cluster) |
|---------|---------------------------|----------------------|
| **Scalability** | You must manually resize the server if traffic spikes. | **Auto-scaling:** K8s automatically spawns more containers across multiple VMs if CPU spikes. |
| **High Availability** | Single point of failure. If the VM crashes, the app goes offline. | **Self-healing:** If a Node (VM) dies, K8s instantly restarts the containers on a healthy Node. |
| **Deployments** | Causes a few seconds of downtime during restarts. | **Zero-Downtime:** Rolling updates seamlessly transition users from old versions to new versions. |
| **Best For** | Prototyping, small teams, testing, and tight budgets. | Millions of users, Enterprise scale, high-availability demands. |

---

## 3. Local Kubernetes Testing Guide (Docker Desktop)

You can run a full Kubernetes cluster on your local machine using Docker Desktop.

### Step 1: Enable Kubernetes
1. Open **Docker Desktop**.
2. Navigate to **Settings** (gear icon) -> **Kubernetes**.
3. Check **Enable Kubernetes**.
4. Choose **Kubeadm** (for a standard 1-node cluster) or **Kind** (if you want to simulate multi-node architectures, requires `containerd` enabled in General settings).
5. Click **Apply & Restart**. *(Note: Downloading the required binaries may take 5–15 minutes).*

### Step 2: Verify the Cluster
Open a PowerShell or Command Prompt terminal and run:
```bash
# Check if the node is Ready
kubectl get nodes

# Check system pods
kubectl get pods -n kube-system
```

### Step 3: Deploy a Test Application
Deploy an NGINX container to verify the cluster works:
```bash
# Create the deployment
kubectl create deployment my-first-app --image=nginx

# Verify the pod is running
kubectl get pods

# Expose the pod to your local browser on port 8080
kubectl port-forward deployment/my-first-app 8080:80
```

### Step 4: View and Cleanup
1. Open a browser and visit **http://localhost:8080** to see the Nginx welcome screen.
2. In your terminal, press `Ctrl+C` to stop the port-forwarding.
3. Clean up the cluster resources:
```bash
kubectl delete deployment my-first-app
```

---

## 4. Moving to Production Kubernetes (AKS / EKS / GKE)

If you are tasked with migrating the `docker-compose.prod.yml` stack to a real production Kubernetes cluster (like Azure Kubernetes Service), here is the Enterprise-grade architectural mapping you will need to implement:

### 1. Database & Cache (PostgreSQL & Redis)
In production K8s, do **not** run databases in standard Pods unless you use StatefulSets with Persistent Volumes (PVs).
- **Best Practice:** Use managed cloud databases instead (e.g., Azure Database for PostgreSQL, Azure Cache for Redis).
- Connect your Kubernetes Django Pods to these external managed databases using Kubernetes **Secrets** for the credentials.

### 2. Backend Web Servers (Django API)
- Deploy using a **Deployment** YAML manifest.
- Set `replicas: 3` (minimum) for High Availability.
- Attach an **HPA (Horizontal Pod Autoscaler)** to scale up to 10+ pods automatically when CPU usage exceeds 70%.

### 3. Machine Learning Background Workers (Celery)
- Deploy using a separate **Deployment** YAML manifest.
- **Node Affinity:** Use Node Affinity rules to assign these heavy ML workers to specific high-CPU/Memory Nodes in your cluster, ensuring they never steal resources from your Django Web API nodes.
- **KEDA (Kubernetes Event-driven Autoscaling):** Instead of scaling based on CPU, use KEDA to autoscale Celery workers based on the number of messages waiting in your Redis queue.

### 4. Networking & SSL (Ingress)
- Replace your standalone NGINX container with an **Ingress Controller** (like NGINX Ingress or Traefik).
- Use **cert-manager** to automatically provision and rotate free SSL/TLS certificates from Let's Encrypt.
- Map your domain (e.g., `api.laguna-ai.com`) directly to the Ingress Controller.

### 5. ConfigMaps and Secrets
- Move everything from your `.env` file into a **ConfigMap** (for non-sensitive data like `ENVIRONMENT=production`) and **Secrets** (for `SECRET_KEY`, `DB_PASSWORD`, etc.).
- Inject these into your Django and Celery pods as environment variables.
