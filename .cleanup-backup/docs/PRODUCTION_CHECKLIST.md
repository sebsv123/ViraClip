# ViraClip Production Deployment Checklist

## ✅ Pre-Deployment Security

- [ ] **Environment Variables**: Copy `.env.example` to `.env` and fill in all required API keys
- [ ] **Change Default Secrets**: 
  - [ ] `BETTER_AUTH_SECRET` - Generate secure random string (min 32 chars)
  - [ ] `BACKEND_AUTH_SECRET` - Generate secure random string (min 32 chars)
  - [ ] `ADMIN_SECRET` - Generate secure random string (min 32 chars)
- [ ] **Database Credentials**: Change default PostgreSQL password in `.env`
  - [ ] `POSTGRES_PASSWORD` (default: `viraclip_password` - CHANGE THIS!)
- [ ] **Redis Security**: Set `REDIS_PASSWORD` for production
- [ ] **Verify .gitignore**: Ensure `.env` files are excluded from version control
- [ ] **API Keys Configured**:
  - [ ] `ASSEMBLY_AI_API_KEY` - Required for transcription
  - [ ] At least one LLM provider (OpenAI/Google/Anthropic/Ollama)
  - [ ] `PEXELS_API_KEY` - Optional, for B-roll
  - [ ] Social media tokens (if using publishing features)

## ✅ Infrastructure Requirements

- [ ] **Hardware**:
  - [ ] Minimum 8GB RAM (16GB recommended)
  - [ ] 30GB+ free disk space
  - [ ] Docker + Docker Compose installed
  - [ ] (Optional) NVIDIA GPU for ComfyUI features
- [ ] **Network**:
  - [ ] Ports 3000 (frontend) and 8000 (backend) available
  - [ ] Firewall rules configured if needed
  - [ ] SSL/TLS certificates if exposing publicly (recommend nginx/Traefik reverse proxy)

## ✅ Configuration Review

- [ ] **Self-Host Mode**: Verify `SELF_HOST=true` in `.env`
- [ ] **CORS Origins**: Update `CORS_ORIGINS` with your production domains
- [ ] **Frontend URL**: Set correct `NEXT_PUBLIC_APP_URL`
- [ ] **Backend URL**: Set correct `NEXT_PUBLIC_API_URL`
- [ ] **Feature Flags**: Review and enable desired features:
  - [ ] `ADMIN_ENABLED` - Admin dashboard
  - [ ] `FEEDBACK_ENABLED` - User feedback
  - [ ] `NOTIFICATIONS_ENABLED` - Browser notifications
  - [ ] `BROLL_ENABLED` - B-roll overlays
- [ ] **Processing Limits**: Configure rate limits and quotas as needed
- [ ] **Whisper Model Size**: Choose appropriate model (tiny/base/small/medium/large)

## ✅ Data Persistence

- [ ] **Docker Volumes**: Verify volume mounts in `docker-compose.yml`
  - [ ] `uploads` - Uploaded videos
  - [ ] `whisper_models` - Whisper model cache
  - [ ] `llm_datasets` - Training datasets
  - [ ] PostgreSQL data volume
  - [ ] Redis data volume
- [ ] **Backup Strategy**: Plan for database backups
- [ ] **Clip Export Path**: Configure `CLIPS_EXPORT_PATH` if needed

## ✅ Deployment Steps

### First-Time Setup

```bash
# 1. Clone repository
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys and secrets

# 3. Build and start services
docker-compose up -d --build

# 4. Verify health
docker-compose ps
docker-compose logs -f
```

### Health Checks

- [ ] **Backend Health**: `curl http://localhost:8000/health`
- [ ] **Frontend Health**: `curl http://localhost:3000/`
- [ ] **PostgreSQL**: Verify database connection
- [ ] **Redis**: Verify cache connection
- [ ] **Workers**: Check worker logs for errors

### Run Tests (Optional but Recommended)

```bash
# Run full test suite
docker exec viraclip-backend sh -c "cd /app && .venv/bin/pytest -q"

# Expected: 2398+ passed, 19 skipped
```

## ✅ Post-Deployment Verification

- [ ] **Create Test Task**: Upload a test video and verify processing
- [ ] **Check Logs**: Monitor for errors in all services
  ```bash
  docker-compose logs -f backend
  docker-compose logs -f frontend
  docker-compose logs -f worker
  ```
- [ ] **Verify Clips Export**: Ensure rendered clips are accessible
- [ ] **Test Authentication**: Create account and verify login
- [ ] **Admin Dashboard**: Access `/admin/login` if enabled

## ✅ Monitoring & Maintenance

- [ ] **Log Aggregation**: Set up log collection (optional)
- [ ] **Metrics**: Configure monitoring (Prometheus/Grafana recommended)
- [ ] **Disk Space**: Monitor available disk space for clips
- [ ] **Database Backups**: Implement automated backup schedule
- [ ] **Update Strategy**: Plan for pulling updates from GitHub

## ✅ Security Hardening (Production)

- [ ] **Reverse Proxy**: Use nginx/Traefik with SSL/TLS
- [ ] **Rate Limiting**: Review and adjust rate limits in `.env`
- [ ] **Network Isolation**: Use Docker networks to isolate services
- [ ] **Disable Sign-Up**: Set `DISABLE_SIGN_UP=true` if needed
- [ ] **Admin Access**: Restrict admin endpoints to trusted IPs
- [ ] **API Authentication**: Ensure all API routes are properly secured
- [ ] **File Upload Limits**: Configure max upload sizes
- [ ] **Content Moderation**: Enable and configure if needed

## ✅ Performance Optimization

- [ ] **Worker Scaling**: Adjust worker count based on load
  ```yaml
  worker:
    deploy:
      replicas: 4  # Increase for more concurrent processing
  ```
- [ ] **Redis Memory**: Configure `maxmemory` and eviction policy
- [ ] **PostgreSQL Tuning**: Optimize based on your workload
- [ ] **Whisper Model**: Balance accuracy vs speed (tiny=fast, large=accurate)
- [ ] **LLM Provider**: Choose based on cost/speed requirements

## ✅ Troubleshooting

### Common Issues

**Workers not processing tasks:**
- Check Redis connection
- Verify worker logs: `docker-compose logs worker`
- Ensure queue is not backed up

**FFmpeg errors:**
- Check disk space
- Verify file permissions on volumes
- Review worker logs for specific errors

**Database connection errors:**
- Verify PostgreSQL is healthy: `docker-compose ps postgres`
- Check credentials in `.env`
- Ensure database initialized: `docker-compose logs postgres`

**API rate limit errors:**
- Adjust rate limits in `.env`
- Check Redis for rate limit keys

## 📊 Production Metrics

**Current Test Coverage:** 45.21% (2398 passing tests)

**API Endpoints:** 100+ routes across 27 phases

**Services:** 12 core services + 50+ feature services

**Supported Features:**
- ✅ AI-powered video clipping
- ✅ Virality scoring
- ✅ Auto-transcription
- ✅ B-roll generation
- ✅ Social media publishing
- ✅ Clip collections
- ✅ Analytics aggregation
- ✅ Content moderation
- ✅ Smart compression
- ✅ And 20+ more...

## 🔗 Additional Resources

- **README.md** - Quick start guide
- **DEPLOY_GUIDE.md** - Detailed deployment instructions
- **ROADMAP.md** - Feature documentation (Phases 1-27)
- **IMPLEMENTATION_SUMMARY.md** - Technical architecture
- **GitHub Issues** - Report bugs and request features

## 🆘 Support

For issues or questions:
1. Check the documentation in `/docs`
2. Review existing GitHub issues
3. Create a new issue with detailed logs
4. Community Discord (if available)

---

**Last Updated:** April 6, 2026
**Version:** Phases 1-27 Complete
**Repository:** https://github.com/sebsv123/ViraClip
