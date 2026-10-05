import subprocess
import os
import tempfile
import sys
import shutil
import logging
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from typing import Type

logger = logging.getLogger(__name__)

class PythonExecutorInput(BaseModel):
    code: str = Field(
        ..., 
        description="The raw Python code string to execute. You MUST print results to stdout using print() to see them."
    )

class PythonExecutorTool(BaseTool):
    name: str = "execute_python"
    description: str = """
    Executes Python code for calculations, data analysis (Pandas/Numpy), and chart generation.
    
    USE THIS TOOL WHEN:
    - You need to compute complex values (statistics, determinants, matrix math).
    - You need to process structured data or CSV/Excel files programmatically.
    - You need to generate visualizations (charts, plots).
    
    RULES:
    1. ALWAYS use print() for any value you want to see. Plain expressions are NOT captured.
    2. Headless Mode: Matplotlib is forced to 'Agg' mode. ALWAYS save plots using plt.savefig('name.png').
    3. Artifacts: Any file saved in the current directory will be moved to /static and a URL provided.
    
    DO NOT:
    - Try to perform complex math mentally. Use the tool.
    - Return answers without executing the code first.
    
    Example:
    User: 'What is the mean of [10, 20, 30]?'
    Tool Input: {"code": "import numpy as np; print(np.mean([10, 20, 30]))"}
    """
    args_schema: Type[BaseModel] = PythonExecutorInput

    def _run(self, code: str) -> str:
        """Internal execution logic."""
        temp_path = None
        try:
            static_dir = "static"
            if not os.path.exists(static_dir):
                os.makedirs(static_dir)
            
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as temp_file:
                # Enforce matplotlib headless mode
                safe_code = "import matplotlib\nmatplotlib.use('Agg')\n" + code
                temp_file.write(safe_code)
                temp_path = temp_file.name
    
            # Run the code using the current Python executable
            result = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=30 
            )
    
            output = ""
            output_files = []
            
            # Move generated artifacts to static/
            cwd_files = [f for f in os.listdir('.') if f.endswith(('.png', '.jpg', '.jpeg', '.pdf'))]
            for f in cwd_files:
                dest = os.path.join(static_dir, f)
                try:
                    shutil.move(f, dest)
                    output_files.append(f)
                except Exception as move_err:
                    logger.warning(f"Failed to move artifact {f}: {move_err}")
    
            if result.stdout:
                stdout_content = result.stdout.strip()
                if len(stdout_content) > 10000:
                    stdout_content = stdout_content[:10000] + "\n\n...[OUTPUT TRUNCATED]..."
                output += f"--- STDOUT ---\n{stdout_content}\n"
                
            if result.stderr:
                stderr_lines = [l for l in result.stderr.strip().split('\n') if 'warning' not in l.lower()]
                if stderr_lines:
                    output += f"--- STDERR ---\n{os.linesep.join(stderr_lines)}\n"
            
            if not output and not output_files:
                output = "Code executed successfully. No console output generated. Ensure you use print() to see results."
            
            if output_files:
                output += "\n--- ARTIFACTS ---\n"
                for f in output_files:
                    output += f"URL: http://localhost:8000/static/{f}\n"
    
            return output.strip()
    
        except subprocess.TimeoutExpired:
            return "Error: Execution timed out after 30 seconds."
        except Exception as e:
            return f"Error executing python code: {str(e)}"
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
