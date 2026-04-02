# 📚 Documentation Index

**Organized documentation for Jubu Backend**

---

## 🎯 Start Here

### New to the project?
1. **[STARTUP_GUIDE.md](STARTUP_GUIDE.md)** - Get backend running in 3 steps
2. **[ARCHITECTURE.md](ARCHITECTURE.md)** - Understand system design and modules
3. **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** - Visual walkthrough of voice pipeline with latency

---

## 📖 Documentation Files

### Core Documentation (Active)

| File | Purpose | When to Read |
|------|---------|--------------|
| **[STARTUP_GUIDE.md](STARTUP_GUIDE.md)** | Quick start instructions | First time setup, troubleshooting startup |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System architecture, modules, API reference | Understanding codebase, debugging, development |
| **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** | Complete voice pipeline, latency breakdown, and instrumentation guide | Performance analysis, optimization, debugging latency, measuring TTFU |

---

## 🗂️ What's in Each Document

### [STARTUP_GUIDE.md](STARTUP_GUIDE.md)
**Purpose:** Get the backend running quickly

**Contents:**
- Prerequisites checklist
- One-command startup (`./test_full_integration.sh`)
- Common issues and fixes
- Log locations
- Configuration variables

**Use when:**
- First time starting the backend
- Backend won't start
- Need to verify services are running

---

### [ARCHITECTURE.md](ARCHITECTURE.md)
**Purpose:** Complete technical reference for the system

**Contents:**
- System overview diagram
- File structure tree
- Module descriptions (livekit_bot.py, jubu_thinker.py, etc.)
- Data flow diagrams
- Latency breakdown table
- API reference
- Configuration guide
- Troubleshooting guide
- Design decisions

**Use when:**
- Understanding how modules interact
- Debugging specific components
- Adding new features
- Reviewing codebase
- Onboarding new developers

---

### [SYSTEM_FLOW.md](SYSTEM_FLOW.md)
**Purpose:** Visual guide to the complete voice conversation flow

**Contents:**
- Step-by-step pipeline visualization
- Detailed latency breakdown (per stage)
- Optimization opportunities
- Tunable parameters
- Performance metrics
- Component responsibilities

**Use when:**
- Analyzing latency issues
- Understanding voice pipeline
- Optimizing performance
- Debugging audio processing
- Explaining system to stakeholders
- Measuring TTFU (Time To First User-heard audio)
- Understanding timestamp coverage
- Implementing monitoring dashboards

---

## 🔍 Finding Information

### "How do I start the backend?"
→ **[STARTUP_GUIDE.md](STARTUP_GUIDE.md)**

### "What does livekit_bot.py do?"
→ **[ARCHITECTURE.md](ARCHITECTURE.md)** → Module Details → livekit_bot.py

### "Why is latency 5 seconds?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Latency Breakdown table

### "What timestamps do I have for measuring latency?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Latency Instrumentation Guide → Current Timestamp Coverage

### "How do I measure TTFU (Time To First User-heard audio)?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Latency Instrumentation Guide → Backend TTFU Calculation

### "What latency metrics should I add?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Latency Instrumentation Guide → Monitoring Metrics

### "How does VAD work?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Step 4: VAD (Voice Activity Detection)
→ **[ARCHITECTURE.md](ARCHITECTURE.md)** → Module Details → livekit_bot.py → Audio Processing Pipeline

### "What Redis channels are used?"
→ **[ARCHITECTURE.md](ARCHITECTURE.md)** → System Overview → REDIS section

### "How do I tune VAD sensitivity?"
→ **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** → Tunable Parameters

### "What's the API endpoint for starting a conversation?"
→ **[ARCHITECTURE.md](ARCHITECTURE.md)** → API Reference → POST /initialize_conversation

### "How do I create evaluation data for AI assistant testing?"
→ **[evaluation/README.md](evaluation/README.md)** → Complete 5-stage pipeline

### "How do I decide how many segments to select per rubric?"
→ **[evaluation/README.md](evaluation/README.md)** → Stage 5 → Step 2: Decide Target Numbers

### "How do I use the segment selection script?"
→ **[evaluation/README.md](evaluation/README.md)** → Stage 5 → Steps 3-4

---

## 📝 Documentation Philosophy

### Principles
1. **Accuracy** - Only document current implementation, archive outdated info
2. **Clarity** - Visual diagrams and examples over walls of text
3. **Actionable** - Every document answers "what should I do next?"
4. **Maintainable** - Fewer files, clearer organization

### When to Update
- ✅ **Update immediately:** Breaking API changes, new modules, major architecture changes
- ⚠️ **Update soon:** Configuration changes, performance optimizations, bug fixes
- ℹ️ **Nice to have:** Minor refactoring, code cleanup

---

## 🎯 Quick Reference

### Common Commands
```bash
# Start backend
./test_full_integration.sh

# View logs
tail -f .api.log .thinker.log .bots.log

# Check status
curl http://localhost:8001/health

# Initialize conversation
curl -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test"}'
```

### Key Files
```
livekit_api.py      # API server
livekit_bot.py      # Voice bot
jubu_thinker.py     # LLM + TTS
bot_manager.py      # Bot lifecycle
test_full_integration.sh  # Start all services

# Evaluation Data Creation
evaluation/README.md  # Complete pipeline documentation
evaluation/datasets/tag_conversations.py          # Stage 1: Rubric tagging
evaluation/datasets/conversation_filtering.py     # Stage 2: Top-K selection
evaluation/datasets/post_process_filtered_conversations.py  # Stage 3: Normalization
evaluation/datasets/segment_conversations.py      # Stage 4: Segmentation
evaluation/datasets/analyze_segment_quality.py    # Stage 5a: Quality analysis
evaluation/datasets/select_evaluation_segments.py # Stage 5b: Selection
```

### Log Files
```
.api.log           # API server
.thinker.log       # LLM + TTS
.bot_manager.log   # Bot manager
.bots.log          # All bots
.recordings/       # Debug audio (if enabled)
```

---

## 🚀 Next Steps After Reading Docs

1. **For developers:**
   - Start backend: `./test_full_integration.sh`
   - Read `ARCHITECTURE.md` Module Details
   - Explore codebase with context

2. **For debugging:**
   - Check `STARTUP_GUIDE.md` Troubleshooting
   - Read `SYSTEM_FLOW.md` to understand pipeline
   - Use logs and Redis monitoring from `ARCHITECTURE.md`

3. **For optimization:**
   - Study `SYSTEM_FLOW.md` Latency Breakdown
   - Review Tunable Parameters
   - Implement optimizations from Optimization Opportunities section

---

**Last Updated:** 2026-02-06  
**Maintained By:** Backend Team

