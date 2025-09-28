#!/usr/bin/env python3
"""
debug_and_fix.py - Debug and fix the specific import issue
Run this to see what's causing the agent_pipeline import error
"""

import sys
import os
from pathlib import Path

def analyze_main_py():
    """Analyze src/main.py for import issues"""
    main_path = Path("src/main.py")
    
    if not main_path.exists():
        print("ERROR: src/main.py not found")
        return False
    
    print("Analyzing src/main.py...")
    content = main_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    # Find all lines mentioning agent_pipeline
    agent_pipeline_lines = []
    for i, line in enumerate(lines, 1):
        if 'agent_pipeline' in line.lower():
            agent_pipeline_lines.append((i, line.strip()))
    
    if agent_pipeline_lines:
        print("Found agent_pipeline references:")
        for line_num, line in agent_pipeline_lines:
            print(f"  Line {line_num}: {line}")
    else:
        print("No agent_pipeline references found")
    
    return content, agent_pipeline_lines

def fix_main_py_thoroughly():
    """Completely fix main.py imports"""
    main_path = Path("src/main.py")
    
    content, agent_lines = analyze_main_py()
    
    print("\nApplying thorough fixes...")
    
    # Complete set of fixes
    fixes = [
        # Import statement fixes
        ("from agent_pipeline import", "from pipelines.agent_pipeline import"),
        ("import agent_pipeline", "from pipelines import agent_pipeline"),
        ("from agent_pipeline ", "from pipelines.agent_pipeline "),
        
        # Usage fixes - these might be the issue
        ("agent_pipeline.run_agent_pipeline", "agent_pipeline.run_agent_pipeline"),
        ("run_agent_pipeline = ", "from pipelines.agent_pipeline import run_agent_pipeline\n# "),
        
        # Vision processor fixes
        ("from vision_processor import", "from models.vision_processor import"),
        ("import vision_processor", "from models import vision_processor"),
        
        # LLM config fixes  
        ("from llm_config import", "from models.llm_config import"),
        ("import llm_config", "from models import llm_config"),
        
        # Directory path fixes
        ('UPLOAD_DIR = "uploads"', 'UPLOAD_DIR = "data/uploads"'),
        ('PROCESSED_DIR = "processed"', 'PROCESSED_DIR = "data/processed"'),
        ("UPLOAD_DIR = 'uploads'", "UPLOAD_DIR = 'data/uploads'"),
        ("PROCESSED_DIR = 'processed'", "PROCESSED_DIR = 'data/processed'"),
    ]
    
    new_content = content
    changes_made = []
    
    for old, new in fixes:
        if old in new_content:
            new_content = new_content.replace(old, new)
            changes_made.append(f"  {old} -> {new}")
    
    # Add the path setup if not present
    if "sys.path.insert" not in new_content:
        path_setup = '''import sys
import os
from pathlib import Path

# Add current directory and project root to Python path
current_file = Path(__file__).resolve()
src_dir = current_file.parent
project_root = src_dir.parent
sys.path.insert(0, str(src_dir))
sys.path.insert(0, str(project_root))
os.chdir(project_root)

'''
        
        # Find where to insert (after docstring, before imports)
        lines = new_content.split('\n')
        insert_pos = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('"""') and not stripped.startswith("'''"):
                if stripped.startswith('import') or stripped.startswith('from'):
                    insert_pos = i
                    break
        
        lines = lines[:insert_pos] + path_setup.strip().split('\n') + [''] + lines[insert_pos:]
        new_content = '\n'.join(lines)
        changes_made.append("  Added path setup")
    
    # Save the fixed file
    main_path.write_text(new_content, encoding='utf-8')
    
    print("Changes made:")
    for change in changes_made:
        print(change)
    
    return True

def check_file_structure():
    """Check that all expected files exist"""
    print("\nChecking file structure...")
    
    expected_files = [
        "src/main.py",
        "src/pipelines/agent_pipeline.py",
        "src/models/vision_processor.py",
        "requirements/requirements.txt",
        "requirements/requirements2.txt"
    ]
    
    missing = []
    for file_path in expected_files:
        if Path(file_path).exists():
            print(f"  OK {file_path}")
        else:
            print(f"  MISSING {file_path}")
            missing.append(file_path)
    
    return len(missing) == 0

def test_import_step_by_step():
    """Test imports step by step to identify the exact issue"""
    print("\nTesting imports step by step...")
    
    # Setup path like our main.py should
    current_dir = Path.cwd()
    src_dir = current_dir / "src"
    sys.path.insert(0, str(current_dir))
    sys.path.insert(0, str(src_dir))
    os.chdir(current_dir)
    
    print(f"Python path: {sys.path[:3]}...")
    print(f"Working dir: {os.getcwd()}")
    
    # Test 1: Can we import the pipeline module?
    try:
        print("Test 1: import src.pipelines.agent_pipeline")
        import src.pipelines.agent_pipeline
        print("  OK Direct import works")
    except Exception as e:
        print(f"  FAIL Direct import: {e}")
        return False
    
    # Test 2: Can we import from pipelines?
    try:
        print("Test 2: from pipelines import agent_pipeline")
        from pipelines import agent_pipeline
        print("  OK From pipelines import works")
    except Exception as e:
        print(f"  FAIL From pipelines: {e}")
        
        # Try alternative
        try:
            print("Test 2b: from src.pipelines import agent_pipeline")
            from src.pipelines import agent_pipeline
            print("  OK Alternative import works")
        except Exception as e2:
            print(f"  FAIL Alternative: {e2}")
            return False
    
    # Test 3: Can we import the main app?
    try:
        print("Test 3: from src.main import app")
        from src.main import app
        print("  OK Main app import works")
        return True
    except Exception as e:
        print(f"  FAIL Main app import: {e}")
        return False

def create_simple_runner():
    """Create a simple runner that should work"""
    runner_content = '''#!/usr/bin/env python3
"""
Simple runner with explicit path setup
"""
import sys
import os
from pathlib import Path

# Explicit path setup
project_root = Path(__file__).parent.resolve()
src_dir = project_root / "src"

# Add paths
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(src_dir))

# Change to project root
os.chdir(project_root)

print(f"Project root: {project_root}")
print(f"Working directory: {os.getcwd()}")
print("Python paths:")
for i, path in enumerate(sys.path[:5]):
    print(f"  {i}: {path}")

try:
    print("\\nTesting imports...")
    
    # Test pipeline import
    print("Importing pipeline...")
    from src.pipelines.agent_pipeline import run_agent_pipeline
    print("OK Pipeline import successful")
    
    # Test main app  
    print("Importing main app...")
    from src.main import app
    print("OK Main app import successful")
    
    # Start server
    print("\\nStarting server...")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
    
except ImportError as e:
    print(f"Import error: {e}")
    print("\\nDebugging info:")
    print(f"Current directory: {os.getcwd()}")
    print(f"src directory exists: {(project_root / 'src').exists()}")
    print(f"main.py exists: {(project_root / 'src' / 'main.py').exists()}")
    print(f"agent_pipeline.py exists: {(project_root / 'src' / 'pipelines' / 'agent_pipeline.py').exists()}")
    
except Exception as e:
    print(f"Other error: {e}")
'''
    
    Path("run_simple.py").write_text(runner_content, encoding='utf-8')
    os.chmod("run_simple.py", 0o755)
    print("Created run_simple.py")

def main():
    """Debug and fix the import issues"""
    print("Debugging import issues...")
    print(f"Working directory: {os.getcwd()}")
    
    # Check structure
    if not check_file_structure():
        print("ERROR: Missing required files")
        return False
    
    # Analyze and fix main.py
    fix_main_py_thoroughly()
    
    # Test imports
    if test_import_step_by_step():
        print("\nSUCCESS: Imports are working!")
        print("Try running: python run.py")
    else:
        print("\nImports still failing. Creating simple runner...")
        create_simple_runner()
        print("Try running: python run_simple.py")
    
    return True

if __name__ == "__main__":
    main()