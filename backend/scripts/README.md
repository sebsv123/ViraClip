# ViraClip Backend Scripts

Utility scripts for development, testing, and maintenance.

---

## 📋 **Available Scripts**

### **validate_environment.py** ✅

Validates ViraClip environment configuration before startup.

**What it checks:**
- ✅ Required directories exist
- ✅ Environment variables set correctly
- ✅ LLM API keys configured
- ✅ Whisper configuration
- ✅ Docker services (if running in container)
- ✅ Python dependencies installed

**Usage:**
```bash
# Check environment
python scripts/validate_environment.py

# Check and auto-create missing directories
python scripts/validate_environment.py --fix
```

**Output:**
- 🟢 Green ✅ = All good
- 🟡 Yellow ⚠️  = Warning (may still work with degraded functionality)
- 🔴 Red ❌ = Error (must fix)

**Example:**
```bash
$ python scripts/validate_environment.py --fix

🔍 ViraClip Environment Validation

==================================================
1. Checking Required Directories
==================================================

✅ temp/uploads
✅ temp/uploads/clips (created)
✅ storage/overlay_cache
⚠️  data/reasoning_traces: Missing (use --fix to create)
...
```

---

### **clean_logs.py** 🧹

Cleans log files by removing null bytes and control characters.

**Usage:**
```bash
# Clean single file
python scripts/clean_logs.py pipeline_output.log

# Clean all logs
python scripts/clean_logs.py *.log
```

**Why needed:**
Some processes may write null bytes to logs, making them unreadable. This script fixes that.

---

## 🚀 **Best Practices**

### **Before First Run**

1. **Validate environment:**
   ```bash
   python scripts/validate_environment.py --fix
   ```

2. **Check output:**
   - If all ✅ green → Ready to go!
   - If ⚠️  yellow warnings → Review and decide if acceptable
   - If ❌ red errors → Must fix before running

3. **Fix common issues:**
   ```bash
   # No LLM API key
   export GROQ_API_KEY="your_key_here"
   
   # Missing directories (auto-fix)
   python scripts/validate_environment.py --fix
   ```

### **During Development**

- Run `validate_environment.py` after pulling updates
- Use `clean_logs.py` if logs become unreadable
- Check environment before reporting bugs

---

## 📚 **Related Documentation**

- **BUGFIXES.md** - Critical bugs and their fixes
- **TROUBLESHOOTING.md** - Common problems and solutions
- **ADDITIONAL_FIXES.md** - Deep audit findings
- **DEVELOPMENT_SETUP.md** - Full setup guide

---

## 🔧 **Script Requirements**

All scripts are standalone and work in both Docker and local environments:

- ✅ Python 3.10+
- ✅ No external dependencies (uses stdlib only)
- ✅ Cross-platform (Windows, Linux, macOS)

---

## 💡 **Tips**

**Quick Health Check:**
```bash
# Full validation
python scripts/validate_environment.py

# If errors, auto-fix directories
python scripts/validate_environment.py --fix

# Set missing env vars
export GROQ_API_KEY="gsk_xxx"
export PEXELS_API_KEY="xxx"
```

**Docker Environment:**
```bash
# Run validation inside container
docker exec viraclip-backend python scripts/validate_environment.py

# Fix from host
docker exec viraclip-backend python scripts/validate_environment.py --fix
```

**Standalone (without Docker):**
```bash
cd backend
python scripts/validate_environment.py --fix
```

---

**Script Maintainer:** ViraClip Development Team  
**Last Updated:** April 9, 2026
