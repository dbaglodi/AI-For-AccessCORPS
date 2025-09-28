# Backend Sync Instructions

## After copying files from Windows:

1. **Run the sync script:**
   ```bash
   python sync_and_fix.py
   ```
   This will:
   - Auto-organize files into correct structure
   - Fix all import paths
   - Install dependencies (Linux only)
   - Create missing config files
   - Set up universal runner

2. **Start the server:**
   ```bash
   python run.py
   ```

3. **Access your app:**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs

## Files Structure After Sync:
```
backend/
├── src/
│   ├── main.py                    # Main FastAPI app
│   ├── config/
│   │   ├── gpu_config.py         # Auto GPU detection  
│   │   └── app_config.py         # App settings
│   ├── models/
│   │   ├── vision_processor.py   # Vision model
│   │   └── llm_config.py         # LLM config
│   └── pipelines/
│       └── agent_pipeline.py     # Main pipeline
├── requirements/
│   ├── requirements.txt          # PyTorch 
│   ├── requirements2.txt         # ML packages
│   └── requirements_web.txt      # Web framework
├── data/                         # Runtime data
└── run.py                        # Universal runner
```

## Troubleshooting:
- Import errors: Run `python sync_and_fix.py` again
- Missing packages: Check requirements files exist
- GPU issues: Check CUDA installation
