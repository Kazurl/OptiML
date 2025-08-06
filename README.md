# OptiML
Project with intention to provide various financial modelling efforts, as well as machine learning models that can provide a benchmark of trained predicted stock price mechanisms.

## OptiML: Installation and Setup Guide
The following guide explains how to set up and run OptiML project locally on your machine. (Installing prerequisites, running locally or on Kubernetes using Docker and Minikube)

## Prerequisites
- Python 3.12+ (for local dev)
- Docker (Download & Install)
- kubectl (Install Guide)
- Minikube (Install Guide)
> Or, to just clone the Project Repo by itself using Git
> - in this case, just skip to **Section 3: Clone the Project Repo**

## 1. Full Setup Instructions
### 1.1 Install Required Tools
1. **Install Docker**
    - Mac:
        - Download Docker Desktop from *[here](https://docs.docker.com/desktop/)*
    - Linux:
        - Use your distribution's package manager
    - Windows:
        - Download Docker Desktop for Windows
2. **Install kubectl**
    - On Mac (via Homebrew):
        -  `brew install kubectl`
        - else: follow the *[official instructions here](https://kubernetes.io/docs/tasks/tools/install-kubectl/)*
3. **Install Minikube**
    - On Mac (via Homebrew):
        - `brew install minikube`
        - else: follow the *[official minikube docs here](https://minikube.sigs.k8s.io/docs/start/)*

### 2 Running the Project (Docker/ Kubernetes-Minikube)
### 2.1 Dockerized Local Run
1. **Build Docker Image**
> `docker build -t <your-dockerhub-username>/optiml:latest .`
2. **Run the Image**
> `docker run -p 8501:8501 <your-dockerhub-username>/optiml:latest`
3. Visit <http://localhost:8501> in your browser

### 2.2 Kubernetes Deployment with Minikube
1. **Start Minikube**
> `minikube start`
2. **Build the Docker image and Push to Docker Hub**
> `docker build -t <your-dockerhub-username>/optiml:latest .`
> `docker push <your-dockerhub-username>/optiml:latest`
> :warning: **Ensure** `image: <your-dockerhub-username>/optiml:latest` in your deployment YAML matches this tag.
3. **Apply Kubernetes Manifests**
> `kubectl apply -f k8s/deployment.yaml`
> `kubectl apply -f k8s/service.yaml`
4. **Access the app**
> `minikube service optiml-app-service`
> This command automatically opens browser to the running app
5. **:wrench: Troubleshooting and Additional Notes**
- Image Not Updating? :thinking:
  Remember to rebuild and push Docker image after any code change, then use
  > `kubectl rollout restart deployment optiml-app`
  to refresh the apop in Kubernetes
- Check Pod Status:
> `kubectl get pods`
> `kubectl describe pod <pod-name>`
- Requirements:
  All Python requirements are in `requirements.txt`
- File Structure Example:
```
> optiml/
> ├── streamlit_app.py
> ├── requirements.txt
> ├── Dockerfile
> ├── k8s/
> │   ├── deployment.yaml
> │   └── service.yaml
> ├── app/
> └── utils/
```
6. **Environment Cleanup**
_Do this when you want to stop running the app_
- **Minikube**
> `minikube stop`
> `minikube delete`
- **Kubernetes resources**
> `kubectl delete -f k8s/deployment.yaml`
> `kubectl delete -f k8s/service.yaml`

7. **Updating the App*
> _Skip this if plainly running app_
After code changes:
> 1. Rebuild and push Docker image
> 2. Restart deployment or re-apply yaml
> 3. Pull latest code on cluster if using CI/CD efforts
> Full processes and commands can be found in __UPDATE_PROCESS.txt__ within project files.

### 2.3 Running on Cloned Project [No Docker/ K8s]
1. **Clone the Project in your console or IDE terminals**
> `git clone https://github.com/Kazurl/OptiML.git`
> `cd optiml`
2. **Set up virtual environment (recommended)**
> `python3.12 -m venv venv`
> `source venv/bin/activate  # mac/linux`
> `# or`
> `.\venv\Scripts\activate  # Windows`
3. **Install dependencies**
> `pip install --upgrade pip`
> `pip install -r requirements.txt`
4. **Run the Streamlit app**
> `streamlit run streamlit_app.py`
5. Automatically opened in browser at <http://localhost:8501>