import os
import zipfile

def create_deploy_zip():
    exclude_dirs = {'.git', 'venv', '__pycache__', 'core/data_lake', 'backtest_data', 'backtest_results', 'logs', '.agents'}
    exclude_extensions = {'.log', '.parquet', '.db', '.pyc', '.zip'}
    
    with zipfile.ZipFile('deploy.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if not any(ex in os.path.join(root, d).replace('\\', '/') for ex in exclude_dirs)]
            
            for file in files:
                if any(file.endswith(ext) for ext in exclude_extensions):
                    continue
                if file == 'deploy.zip':
                    continue
                
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, '.')
                print(f"Adding: {arcname}")
                zipf.write(file_path, arcname)

if __name__ == '__main__':
    create_deploy_zip()
    print("deploy.zip created successfully.")
