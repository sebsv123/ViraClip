# ViraClip Deployment Guide

Complete deployment guide for ViraClip - AI-powered viral clip generation platform.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Local Development](#local-development)
4. [Production Deployment](#production-deployment)
5. [Docker Deployment](#docker-deployment)
6. [Kubernetes Deployment](#kubernetes-deployment)
7. [Environment Configuration](#environment-configuration)
8. [Monitoring & Maintenance](#monitoring--maintenance)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

**Minimum Requirements:**
- CPU: 4 cores (8+ recommended for production)
- RAM: 8GB (16GB+ recommended)
- Storage: 50GB SSD (200GB+ for video processing)
- OS: Linux (Ubuntu 20.04+), macOS, or Windows with WSL2

**Recommended for Production:**
- CPU: 8+ cores
- RAM: 32GB+
- GPU: NVIDIA GPU with CUDA support (for AI acceleration)
- Storage: 500GB+ NVMe SSD
- Network: 100Mbps+ symmetric

### Required Software

- **Docker** 20.10+ and Docker Compose
- **Python** 3.9+
- **Node.js** 18+
- **PostgreSQL** 14+
- **Redis** 6+
- **FFmpeg** 5.0+

### Cloud Provider Setup (Optional)

For cloud deployment, you'll need:
- AWS Account (EC2, S3, RDS) OR
- Google Cloud Platform OR
- Azure OR
- Any VPS provider (DigitalOcean, Linode, etc.)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer                         │
│                    (Nginx/CloudFlare)                   │
└──────────────────┬──────────────────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    │                             │
┌───▼────┐                  ┌─────▼────┐
│Frontend│                  │  Backend │
│Next.js │◄────────────────►│ FastAPI  │
└────────┘                  └────┬─────┘
                                  │
          ┌───────────────────────┼──────────────────┐
          │                       │                  │
     ┌────▼────┐            ┌─────▼────┐      ┌────▼────┐
     │PostgreSQL│            │  Redis   │      │  MinIO  │
     │  (Data)  │            │ (Queue)  │      │(Storage)│
     └─────────┘             └──────────┘      └─────────┘
```

---

## Local Development

### 1. Clone Repository

```bash
git clone https://github.com/your-org/viraclip.git
cd viraclip
```

### 2. Backend Setup

```bash
# Navigate to backend
cd backend

# Create virtual environment
python -m venv .venv

# Activate environment
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### 3. Frontend Setup

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Copy environment file
cp .env.example .env.local

# Edit environment variables
nano .env.local
```

### 4. Database Setup

```bash
# Start PostgreSQL and Redis
docker-compose up -d postgres redis

# Run database migrations
cd backend
alembic upgrade head

# Seed initial data
python scripts/seed_data.py
```

### 5. Start Development Servers

```bash
# Terminal 1: Backend
cd backend
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: Worker (optional)
cd backend
python -m src.workers.tasks
```

### 6. Access Application

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

---

## Production Deployment

### Option 1: Docker Compose (Recommended for Small/Medium)

```bash
# Clone repository
git clone https://github.com/your-org/viraclip.git
cd viraclip

# Copy production environment
cp .env.production.example .env

# Edit production environment
nano .env

# Build and start services
docker-compose -f docker-compose.prod.yml up -d --build

# Run migrations
docker-compose exec backend alembic upgrade head

# Create admin user
docker-compose exec backend python scripts/create_admin.py
```

### Option 2: Manual Deployment

#### Backend Deployment

```bash
# Server setup
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx ffmpeg

# Create app directory
sudo mkdir -p /opt/viraclip/backend
sudo chown -R $USER:$USER /opt/viraclip

# Copy application
cd backend
pip install -r requirements.txt

# Create systemd service
sudo nano /etc/systemd/system/viraclip-backend.service
```

Service file content:
```ini
[Unit]
Description=ViraClip Backend
After=network.target

[Service]
Type=simple
User=viraclip
WorkingDirectory=/opt/viraclip/backend
Environment="PATH=/opt/viraclip/backend/.venv/bin"
Environment="APP_ENV=production"
ExecStart=/opt/viraclip/backend/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable viraclip-backend
sudo systemctl start viraclip-backend

# Check status
sudo systemctl status viraclip-backend
```

#### Frontend Deployment

```bash
# Build production bundle
cd frontend
npm ci
npm run build

# Serve with Nginx
sudo cp -r dist /var/www/viraclip/
sudo nano /etc/nginx/sites-available/viraclip
```

Nginx configuration:
```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Frontend
    location / {
        root /var/www/viraclip/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSocket support
    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/viraclip /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Setup SSL with Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (1.24+)
- kubectl configured
- Helm 3.x

### Deployment Steps

```bash
# Create namespace
kubectl create namespace viraclip

# Apply configurations
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/frontend.yaml
kubectl apply -f k8s/ingress.yaml

# Verify deployment
kubectl get pods -n viraclip
kubectl get svc -n viraclip
kubectl get ingress -n viraclip

# Scale backend
kubectl scale deployment backend --replicas=3 -n viraclip
```

### Helm Chart

```bash
# Install with Helm
helm upgrade --install viraclip ./helm/viraclip \
  --namespace viraclip \
  --create-namespace \
  --set ingress.host=your-domain.com \
  --set backend.replicas=3
```

---

## Environment Configuration

### Required Environment Variables

#### Backend (.env)

```bash
# Application
APP_ENV=production
DEBUG=false
SECRET_KEY=your-secure-secret-key-here

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/viraclip
DATABASE_POOL_SIZE=20

# Redis
REDIS_URL=redis://localhost:6379/0

# Storage
STORAGE_TYPE=s3  # or local, minio
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_BUCKET_NAME=viraclip-uploads
AWS_REGION=us-east-1

# AI/ML Services
ASSEMBLY_AI_API_KEY=your-assembly-ai-key
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key

# Video Processing
FFMPEG_PATH=/usr/bin/ffmpeg
MAX_VIDEO_SIZE=1073741824  # 1GB
PROCESSING_TIMEOUT=1800  # 30 minutes

# Security
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CORS_ORIGINS=https://your-domain.com

# Monitoring
SENTRY_DSN=your-sentry-dsn
LOG_LEVEL=INFO
```

#### Frontend (.env.local)

```bash
# API
NEXT_PUBLIC_API_URL=https://your-domain.com/api
NEXT_PUBLIC_WS_URL=wss://your-domain.com/ws

# Authentication
NEXT_PUBLIC_AUTH_PROVIDER=email  # or google, github

# Features
NEXT_PUBLIC_ENABLE_REALTIME=true
NEXT_PUBLIC_ENABLE_BLOCKCHAIN=true
NEXT_PUBLIC_MAX_UPLOAD_SIZE=104857600  # 100MB

# Analytics
NEXT_PUBLIC_GA_ID=your-google-analytics-id
```

---

## Monitoring & Maintenance

### Health Checks

```bash
# Backend health
curl https://your-domain.com/api/health

# Database health
curl https://your-domain.com/api/health/db

# Full system check
curl https://your-domain.com/api/health/detailed
```

### Log Management

```bash
# View backend logs
sudo journalctl -u viraclip-backend -f

# View nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Docker logs
docker-compose logs -f backend
```

### Backup Strategy

```bash
# Database backup
pg_dump -Fc viraclip_db > backup_$(date +%Y%m%d).dump

# Upload to S3
aws s3 cp backup_*.dump s3://viraclip-backups/

# Automated backup script
0 2 * * * /opt/viraclip/scripts/backup.sh
```

### Performance Monitoring

```bash
# Resource usage
docker stats

# Database performance
psql -c "SELECT * FROM pg_stat_activity;"

# Redis monitoring
redis-cli info stats
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Errors

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Verify connection
psql -U viraclip -d viraclip_db -c "SELECT 1;"

# Check max connections
psql -c "SHOW max_connections;"
```

#### 2. Video Processing Failures

```bash
# Check FFmpeg
ffmpeg -version

# Verify disk space
df -h

# Check processing logs
docker-compose logs backend | grep -i error
```

#### 3. Memory Issues

```bash
# Monitor memory
free -h

# Check for memory leaks
docker stats --no-stream

# Adjust worker count in .env
WORKER_PROCESSES=2
```

#### 4. API Rate Limiting

```bash
# Check rate limit configuration
cat backend/src/config.py | grep RATE_LIMIT

# Review nginx rate limiting
sudo nginx -T | grep limit_req
```

### Getting Help

- **Documentation**: https://docs.viraclip.io
- **GitHub Issues**: https://github.com/your-org/viraclip/issues
- **Community Discord**: https://discord.gg/viraclip
- **Email Support**: support@viraclip.io

---

## Security Considerations

1. **SSL/TLS**: Always use HTTPS in production
2. **Secrets**: Use secret management (AWS Secrets Manager, Vault)
3. **Firewall**: Only expose necessary ports
4. **Updates**: Keep dependencies updated
5. **Backups**: Encrypt backups at rest
6. **Monitoring**: Set up alerts for suspicious activity

---

## Scaling Guide

### Horizontal Scaling

```bash
# Scale backend instances
kubectl scale deployment backend --replicas=5

# Add load balancer
kubectl apply -f k8s/loadbalancer.yaml

# Database read replicas
kubectl apply -f k8s/postgres-replica.yaml
```

### Vertical Scaling

```bash
# Increase CPU/Memory limits
kubectl patch deployment backend -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","resources":{"limits":{"cpu":"4","memory":"8Gi"}}}]}}}}'
```

---

## Next Steps

1. **Configure CDN**: Set up CloudFlare or AWS CloudFront
2. **Setup CI/CD**: GitHub Actions or GitLab CI
3. **Monitoring**: Install Datadog or Grafana
4. **Alerting**: Configure PagerDuty or Opsgenie
5. **Documentation**: API docs with Swagger/OpenAPI

---

**Version**: 1.0.0  
**Last Updated**: January 2024  
**Maintained by**: ViraClip Team
