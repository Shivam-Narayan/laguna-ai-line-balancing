import os
import re

APPS_DIR = os.path.join(os.path.dirname(__file__), "apps")

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    needs_logging = False
    for line in lines:
        if 'print(' in line or 'except Exception as e:' in line:
            needs_logging = True
            break

    if not needs_logging:
        return

    # Check if logging is already imported
    has_import = any('import logging' in line for line in lines)
    has_logger = any('logger = logging.getLogger' in line for line in lines)

    new_lines = []
    
    # Add imports at the top
    if not has_import:
        # Find first non-empty, non-comment line or just put at top
        for i, line in enumerate(lines):
            if not line.startswith('#') and line.strip():
                lines.insert(i, 'from core.logger import configure_logging\n')
                if not has_logger:
                    lines.insert(i+1, 'logger = configure_logging(__name__)\n\n')
                break

    for i, line in enumerate(lines):
        # Very basic replacement for print( -> logger.info(
        # Note: this might break if print spans multiple lines or has kwargs like end=""
        if 'print(' in line and not line.strip().startswith('#'):
            # Replace print( with logger.info(
            # Using regex to match print( properly
            line = re.sub(r'\bprint\(', 'logger.info(', line)
        
        # Replace except Exception as e: ... print(e) -> logger.exception(e)
        if 'except Exception as e:' in line and not line.strip().startswith('#'):
            # We don't automatically change the next line here to keep it simple,
            # but since print( becomes logger.info(, it will be logger.info(e)
            # We can optionally try to replace logger.info(e) with logger.exception(e)
            pass

        new_lines.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"Refactored: {filepath}")

for root, _, files in os.walk(APPS_DIR):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))

print("Refactoring complete.")
